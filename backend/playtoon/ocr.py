"""OCR with OpenCV preprocessing.

Default engine: RapidOCR (PaddleOCR models on ONNX Runtime; no native install needed).
Optional engine: Tesseract (if the binary + `ara`/`fra` traineddata are installed) for
Arabic-script and accent-heavy screens.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class TextBox:
    text: str
    conf: float
    x: int
    y: int
    w: int
    h: int

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def preprocess(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Normalise an arbitrary screenshot / frame for OCR. Returns (image, scale)."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    h, w = img.shape[:2]
    scale = 1.0
    # Small text is the #1 OCR failure; upscale small images, downscale huge ones.
    if max(h, w) < 900:
        scale = 900 / max(h, w)
    elif max(h, w) > 2200:
        scale = 2200 / max(h, w)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
    # Contrast-limited histogram equalisation on luminance (handles washed-out video frames)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    img = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    # Light edge-preserving smoothing for compression artefacts (cheap, unlike NL-means)
    img = cv2.bilateralFilter(img, 5, 30, 5)
    return img, scale


class OcrEngine:
    def recognize(self, img: np.ndarray) -> list[TextBox]:
        raise NotImplementedError


class RapidOcrEngine(OcrEngine):
    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR
        # 'max' limit: long thin bands (region OCR) are not blown up to 736px on their short side
        self._ocr = RapidOCR(det_limit_type="max", det_limit_side_len=960)
        self._lock = threading.Lock()   # ORT session is not re-entrant across threads here

    def recognize(self, img: np.ndarray) -> list[TextBox]:
        proc, scale = preprocess(img)
        with self._lock:
            result, _ = self._ocr(proc, use_cls=False)   # screen text is upright
        boxes: list[TextBox] = []
        for pts, text, conf in result or []:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            boxes.append(TextBox(text=text.strip(), conf=float(conf),
                                 x=int(min(xs) / scale), y=int(min(ys) / scale),
                                 w=int((max(xs) - min(xs)) / scale), h=int((max(ys) - min(ys)) / scale)))
        return [b for b in boxes if b.text]


class TesseractEngine(OcrEngine):
    def __init__(self, langs: str = "eng+fra+ara") -> None:
        self.bin = shutil.which("tesseract")
        if not self.bin:
            raise RuntimeError("tesseract not installed")
        self.langs = langs

    def recognize(self, img: np.ndarray) -> list[TextBox]:
        proc, scale = preprocess(img)
        gray = cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            cv2.imwrite(f.name, gray)
            out = subprocess.run([self.bin, f.name, "stdout", "-l", self.langs, "tsv"],
                                 capture_output=True, text=True, encoding="utf-8").stdout
        lines: dict[tuple, TextBox] = {}
        for row in out.splitlines()[1:]:
            c = row.split("\t")
            if len(c) < 12 or not c[11].strip() or float(c[10]) < 0:
                continue
            key = (c[2], c[3], c[4])
            x, y, w, h = (int(int(v) / scale) for v in c[6:10])
            if key in lines:
                b = lines[key]
                nx, ny = min(b.x, x), min(b.y, y)
                b.w, b.h = max(b.x + b.w, x + w) - nx, max(b.y + b.h, y + h) - ny
                b.x, b.y = nx, ny
                b.text += " " + c[11]
                b.conf = min(b.conf, float(c[10]) / 100)
            else:
                lines[key] = TextBox(c[11], float(c[10]) / 100, x, y, w, h)
        return list(lines.values())


_engine: OcrEngine | None = None
_engine_lock = threading.Lock()


def get_engine(preferred: str = "auto") -> OcrEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            if preferred in ("tesseract",) or (preferred == "auto" and shutil.which("tesseract")):
                try:
                    _engine = TesseractEngine()
                    log.info("OCR engine: tesseract")
                except RuntimeError:
                    _engine = None
            if _engine is None:
                _engine = RapidOcrEngine()
                log.info("OCR engine: rapidocr")
        return _engine


def boxes_to_text(boxes: list[TextBox]) -> tuple[str, float]:
    """Reading-order reconstruction: group boxes into lines by vertical overlap, sort left->right
    (right->left for Arabic lines). Returns text and mean confidence."""
    if not boxes:
        return "", 0.0
    boxes = sorted(boxes, key=lambda b: (b.cy, b.x))
    lines: list[list[TextBox]] = []
    for b in boxes:
        if lines:
            last = lines[-1]
            ref = sum(x.cy for x in last) / len(last)
            if abs(b.cy - ref) < 0.6 * max(b.h, min(x.h for x in last)):
                last.append(b)
                continue
        lines.append([b])
    # Split each line where a wide horizontal gap separates boxes, then group the resulting segments
    # into columns by horizontal overlap. Multi-column layouts (quiz beside a chat panel) are then
    # read column by column instead of interleaving their lines.
    med_h = float(np.median([b.h for b in boxes])) or 10.0
    segments: list[list[TextBox]] = []
    for ln in lines:
        ln.sort(key=lambda b: b.x)
        cur = [ln[0]]
        for b in ln[1:]:
            prev = cur[-1]
            if b.x - (prev.x + prev.w) > 2.5 * med_h:
                segments.append(cur)
                cur = [b]
            else:
                cur.append(b)
        segments.append(cur)
    columns: list[dict] = []
    for seg in sorted(segments, key=lambda s: (s[0].x, s[0].y)):
        x0, x1 = seg[0].x, max(b.x + b.w for b in seg)
        col = next((c for c in columns if min(x1, c["x1"]) - max(x0, c["x0"]) > 0), None)
        if col is None:
            columns.append({"x0": x0, "x1": x1, "segs": [seg]})
        else:
            col["x0"], col["x1"] = min(col["x0"], x0), max(col["x1"], x1)
            col["segs"].append(seg)
    # merge columns that ended up overlapping after growing
    merged: list[dict] = []
    for c in sorted(columns, key=lambda c: c["x0"]):
        if merged and c["x0"] < merged[-1]["x1"]:
            merged[-1]["x1"] = max(merged[-1]["x1"], c["x1"])
            merged[-1]["segs"] += c["segs"]
        else:
            merged.append(c)
    rtl_page = sum(any("؀" <= ch <= "ۿ" for ch in b.text) for b in boxes) > len(boxes) / 2
    if rtl_page:
        merged.reverse()
    out = []
    for c in merged:
        for seg in sorted(c["segs"], key=lambda s: min(b.y for b in s)):
            rtl = sum(any("؀" <= ch <= "ۿ" for ch in b.text) for b in seg) > len(seg) / 2
            seg.sort(key=lambda b: -b.x if rtl else b.x)
            out.append(" ".join(b.text for b in seg))
        out.append("")
    conf = float(np.average([b.conf for b in boxes], weights=[max(len(b.text), 1) for b in boxes]))
    return "\n".join(out).strip(), conf
