"""Image and video question recognition.

Video/screen streams are expensive to OCR, so a frame is only OCR'd when:
  1. its content differs from the last OCR'd frame (frame-change detection), and
  2. motion has settled (or a max-wait expired) so animations are read once, not 30x/s, and
  3. the frame is not a near-duplicate (perceptual hash) of a recently OCR'd frame.
When only a sub-region changed, only that region is OCR'd and merged into the tracked text regions.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import cv2
import numpy as np

from .models import Modality, Observation
from .ocr import TextBox, boxes_to_text, get_engine
from .text_utils import extract_questions

log = logging.getLogger(__name__)

SMALL_W = 320


def _small_gray(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    g = cv2.resize(g, (SMALL_W, max(1, int(h * SMALL_W / w))), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(g, (3, 3), 0)


def dhash(gray_small: np.ndarray) -> int:
    r = cv2.resize(gray_small, (17, 16), interpolation=cv2.INTER_AREA)
    bits = (r[:, 1:] > r[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _iou(a: TextBox, b: TextBox) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union else 0.0


def observations_from_text(text: str, conf: float, origin: str, stream_key: str | None,
                           modality: Modality = Modality.VISUAL, lang_hint: str | None = None,
                           meta: dict | None = None) -> list[Observation]:
    now = time.monotonic()
    obs = []
    for q in extract_questions(text, lang_hint, final=bool((meta or {}).get("final"))):
        obs.append(Observation(text=q.text, modality=modality, confidence=conf, language=q.language,
                               options=q.options, complete=q.complete, origin=origin,
                               stream_key=stream_key, metadata={**(meta or {}), "preamble": q.preamble},
                               observed_at=now))
    return obs


def process_image(img: np.ndarray, origin: str = "image", lang_hint: str | None = None) -> tuple[str, list[Observation]]:
    boxes = get_engine().recognize(img)
    text, conf = boxes_to_text(boxes)
    # a single still image is final content: nothing more will render into it
    return text, observations_from_text(text, conf, origin, stream_key=None, lang_hint=lang_hint, meta={"final": True})


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("unsupported or corrupt image")
    return img


@dataclass
class Track:
    tid: int
    box: TextBox
    first_frame: int
    last_frame: int


@dataclass
class VideoStats:
    frames_seen: int = 0
    skipped_static: int = 0
    skipped_in_motion: int = 0
    dedup_hits: int = 0
    ocr_full: int = 0
    ocr_region: int = 0
    text_changes: int = 0

    @property
    def ocr_calls(self) -> int:
        return self.ocr_full + self.ocr_region

    def to_dict(self) -> dict:
        return {**self.__dict__, "ocr_calls": self.ocr_calls}


@dataclass
class VideoStreamProcessor:
    stream_id: str
    change_threshold: float = 0.003     # fraction of pixels that must change vs last OCR'd frame
    motion_threshold: float = 0.002     # below this vs previous sample = "settled"
    max_wait_s: float = 1.0             # OCR anyway if content keeps moving this long
    region_max_fraction: float = 0.45   # region-only OCR when change bbox is smaller than this
    lang_hint: str | None = None
    stats: VideoStats = field(default_factory=VideoStats)

    def __post_init__(self) -> None:
        self._prev_small: np.ndarray | None = None
        self._ocr_small: np.ndarray | None = None
        self._dirty_since: float | None = None
        self._tracks: list[Track] = []
        self._next_tid = 1
        self._last_text = ""
        self._hash_cache: OrderedDict[int, list[TextBox]] = OrderedDict()

    @property
    def tracks(self) -> list[Track]:
        return self._tracks

    def _assign_tracks(self, boxes: list[TextBox], frame_idx: int, region: tuple[int, int, int, int] | None) -> None:
        if region is None:
            keep: list[Track] = []
        else:
            rx, ry, rw, rh = region
            keep = [t for t in self._tracks
                    if not (t.box.x < rx + rw and t.box.x + t.box.w > rx and t.box.y < ry + rh and t.box.y + t.box.h > ry)]
        old = [t for t in self._tracks if t not in keep]
        new_tracks = list(keep)
        for b in boxes:
            match = max(old, key=lambda t: _iou(t.box, b), default=None)
            if match is not None and _iou(match.box, b) > 0.3:
                old.remove(match)
                new_tracks.append(Track(match.tid, b, match.first_frame, frame_idx))
            else:
                new_tracks.append(Track(self._next_tid, b, frame_idx, frame_idx))
                self._next_tid += 1
        self._tracks = new_tracks

    @staticmethod
    def _bands(mask: np.ndarray, gap: int = 4, pad: int = 3) -> list[tuple[int, int]]:
        """Horizontal bands (row ranges, small-image coords) containing changed pixels. Text is laid
        out in lines, so re-OCR'ing whole-width bands keeps partially changed lines intact
        (e.g. a typewriter effect only changes the end of a line)."""
        rows = np.flatnonzero(mask.sum(axis=1) >= 2)
        if rows.size == 0:
            return []
        bands, start, prev = [], rows[0], rows[0]
        for r in rows[1:]:
            if r - prev > gap:
                bands.append((start, prev))
                start = r
            prev = r
        bands.append((start, prev))
        hmax = mask.shape[0] - 1
        return [(max(0, a - pad), min(hmax, b + pad)) for a, b in bands]

    def flush(self, frame: np.ndarray, frame_idx: int, t: float, origin_prefix: str = "video") -> list[Observation]:
        """End of stream: a change that was still animating on the last frame must not be lost."""
        if self._dirty_since is None:
            return []
        self.stats.frames_seen -= 1
        self._dirty_since = t - self.max_wait_s - 1     # force: treat as waited long enough
        return self.process_frame(frame, frame_idx, t, origin_prefix)

    def process_frame(self, frame: np.ndarray, frame_idx: int, t: float, origin_prefix: str = "video") -> list[Observation]:
        self.stats.frames_seen += 1
        small = _small_gray(frame)
        first = self._ocr_small is None or self._ocr_small.shape != small.shape
        motion_mask = None if self._prev_small is None or self._prev_small.shape != small.shape else \
            cv2.absdiff(small, self._prev_small) > 25
        self._prev_small = small
        h, w = frame.shape[:2]
        sy = h / small.shape[0]

        if first:
            bands_todo, full = [(0, small.shape[0] - 1)], True
        else:
            diff_mask = cv2.absdiff(small, self._ocr_small) > 25
            # rows covered by known decorative animation (moving, never contained text) are ignored
            self._decor = [(a, b, until) for a, b, until in getattr(self, "_decor", []) if until > t]
            for a, b, _ in self._decor:
                diff_mask[a:b + 1] = False
            if diff_mask.mean() < self.change_threshold:
                self._dirty_since = None
                self.stats.skipped_static += 1
                return []
            bands = self._bands(diff_mask)
            if self._dirty_since is None:
                self._dirty_since = t
            waited = (t - self._dirty_since) >= self.max_wait_s

            def settled(b):
                return motion_mask is None or motion_mask[b[0]:b[1] + 1].mean() < 0.01
            bands_todo = [b for b in bands if settled(b) or waited]
            if not bands_todo:
                self.stats.skipped_in_motion += 1      # still animating; wait for it to settle
                return []
            frac = sum(b - a + 1 for a, b in bands_todo) / small.shape[0]
            full = frac > self.region_max_fraction or not self._tracks

        engine = get_engine()
        region = None
        if full:
            hsh = dhash(small)
            cached = next((v for k, v in self._hash_cache.items() if hamming(k, hsh) <= 3), None)
            if cached is not None:
                self.stats.dedup_hits += 1
                boxes = cached
            else:
                boxes = engine.recognize(frame)
                self.stats.ocr_full += 1
                self._hash_cache[hsh] = boxes
                if len(self._hash_cache) > 64:
                    self._hash_cache.popitem(last=False)
            self._assign_tracks(boxes, frame_idx, None)
            self._ocr_small = small.copy()
        else:
            for a, b in bands_todo:
                y0, y1 = int(a * sy), min(h, int((b + 1) * sy))
                region = (0, y0, w, y1 - y0)
                boxes = [TextBox(bx.text, bx.conf, bx.x, bx.y + y0, bx.w, bx.h)
                         for bx in engine.recognize(frame[y0:y1])]
                self.stats.ocr_region += 1
                self._assign_tracks(boxes, frame_idx, region)
                self._ocr_small[a:b + 1] = small[a:b + 1]
                # strongly moving band with no text (e.g. a sliding graphic): ignore it briefly.
                # Subtle background shimmer does not qualify, so text appearing there is still seen.
                if not boxes and motion_mask is not None and motion_mask[a:b + 1].mean() >= 0.05:
                    self._decor.append((a, b, t + 2.0))
        self._dirty_since = None
        text, conf = boxes_to_text([tr.box for tr in self._tracks])
        if text == self._last_text:
            return []
        self._last_text = text
        self.stats.text_changes += 1
        return observations_from_text(text, conf, f"{origin_prefix}:{self.stream_id}@frame{frame_idx}",
                                      stream_key=f"{origin_prefix}:{self.stream_id}", lang_hint=self.lang_hint,
                                      meta={"frame": frame_idx, "t": round(t, 2),
                                            "region_ocr": region is not None})


def iter_video(path: str, sample_fps: float = 5.0):
    """Yield (frame_idx, t_seconds, frame) sampled at ~sample_fps."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"cannot open video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / sample_fps)))
    idx = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    yield idx, idx / fps, frame
            idx += 1
    finally:
        cap.release()
