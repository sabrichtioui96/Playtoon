"""Spoken-question pipeline:  PCM16 -> noise gate + WebRTC VAD -> utterance segments ->
Whisper (language auto-detected among en/fr/ar, never translated) -> question assembler that joins
multi-sentence / paused questions and rejects incomplete speech."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import webrtcvad

from .models import Modality, Observation
from .text_utils import detect_language, extract_questions, looks_incomplete, starts_like_question

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
FRAME_BYTES = FRAME_SAMPLES * 2
SUPPORTED_LANGS = ("en", "fr", "ar")


@dataclass
class SegmentEvent:
    kind: str                  # "speech_start" | "segment"
    audio: np.ndarray | None = None   # float32 [-1,1] for "segment"
    start_s: float = 0.0
    end_s: float = 0.0


class AudioSegmenter:
    """Streaming endpointer. Speech starts when >=60% of a 300 ms window is voiced; it ends after
    `silence_ms` of non-speech. A frame only counts as voiced when WebRTC VAD says so AND its
    energy is clearly above an adaptive noise floor, which suppresses steady background noise
    (fans, crowd murmur) that VAD alone tends to accept."""

    def __init__(self, aggressiveness: int = 2, silence_ms: int = 700, pre_roll_ms: int = 300,
                 max_segment_s: float = 30.0, min_speech_ms: int = 300, noise_margin_db: float = 6.0):
        self.vad = webrtcvad.Vad(aggressiveness)
        self.silence_frames = silence_ms // FRAME_MS
        self.pre_roll = deque(maxlen=pre_roll_ms // FRAME_MS)
        self.window = deque(maxlen=10)
        self.max_frames = int(max_segment_s * 1000 / FRAME_MS)
        self.min_frames = min_speech_ms // FRAME_MS
        self.noise_margin = 10 ** (noise_margin_db / 20)
        self.noise_floor = 1e-3
        self._buf = b""
        self._in_speech = False
        self._frames: list[np.ndarray] = []
        self._voiced_count = 0
        self._silence_run = 0
        self._t = 0.0
        self._seg_start = 0.0
        self._hp_prev_x = 0.0
        self._hp_prev_y = 0.0

    def _highpass(self, x: np.ndarray) -> np.ndarray:
        # 1st-order high-pass ~100 Hz: removes rumble / DC offset before energy & VAD
        a = 0.96
        y = np.empty_like(x)
        px, py = self._hp_prev_x, self._hp_prev_y
        for i in range(len(x)):
            py = a * (py + x[i] - px)
            px = x[i]
            y[i] = py
        self._hp_prev_x, self._hp_prev_y = px, py
        return y

    def _frame_voiced(self, frame_bytes: bytes, f: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(f * f)) + 1e-9)
        vad = self.vad.is_speech(frame_bytes, SAMPLE_RATE)
        voiced = vad and rms > self.noise_floor * self.noise_margin
        if not voiced:   # track noise floor only on non-speech frames (fast attack down, slow rise)
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms if rms > self.noise_floor else 0.7 * self.noise_floor + 0.3 * rms
            self.noise_floor = max(self.noise_floor, 2e-4)
        return voiced

    def feed(self, pcm16: bytes) -> list[SegmentEvent]:
        events: list[SegmentEvent] = []
        self._buf += pcm16
        while len(self._buf) >= FRAME_BYTES:
            raw, self._buf = self._buf[:FRAME_BYTES], self._buf[FRAME_BYTES:]
            f = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            f_hp = self._highpass(f)
            voiced = self._frame_voiced((np.clip(f_hp, -1, 1) * 32767).astype(np.int16).tobytes(), f_hp)
            self._t += FRAME_MS / 1000
            if not self._in_speech:
                self.pre_roll.append(f)
                self.window.append(voiced)
                if len(self.window) == self.window.maxlen and sum(self.window) >= 6:
                    self._in_speech = True
                    self._frames = list(self.pre_roll)
                    self._voiced_count = sum(self.window)
                    self._silence_run = 0
                    self._seg_start = self._t - len(self._frames) * FRAME_MS / 1000
                    events.append(SegmentEvent("speech_start", start_s=self._seg_start))
            else:
                self._frames.append(f)
                if voiced:
                    self._voiced_count += 1
                    self._silence_run = 0
                else:
                    self._silence_run += 1
                if self._silence_run >= self.silence_frames or len(self._frames) >= self.max_frames:
                    events.extend(self._close())
        return events

    def _close(self) -> list[SegmentEvent]:
        frames = self._frames[: len(self._frames) - max(0, self._silence_run - 8)]  # keep 240 ms tail
        self._in_speech = False
        self.window.clear()
        self.pre_roll.clear()
        self._frames = []
        if self._voiced_count < self.min_frames:
            return []                              # click / cough, not speech
        audio = np.concatenate(frames)
        return [SegmentEvent("segment", audio=audio, start_s=self._seg_start, end_s=self._t)]

    def flush(self) -> list[SegmentEvent]:
        return self._close() if self._in_speech else []


@dataclass
class Transcript:
    text: str
    language: str
    language_prob: float
    confidence: float
    duration_s: float
    elapsed_ms: int


class Transcriber:
    """faster-whisper wrapper. Language is detected on the segment and restricted to the
    supported set; task is always 'transcribe' (original language preserved, no translation)."""

    def __init__(self, model_size: str = "small", device: str = "cpu", compute_type: str = "int8"):
        from faster_whisper import WhisperModel
        self.model_size = model_size
        import os
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type,
                                  cpu_threads=max(4, (os.cpu_count() or 8) // 2))
        self._lock = threading.Lock()

    def detect_language(self, audio: np.ndarray, allowed=SUPPORTED_LANGS) -> tuple[str, float]:
        _, _, all_probs = self.model.detect_language(audio)
        probs = {lang: p for lang, p in all_probs if lang in allowed}
        if not probs:
            return allowed[0], 0.0
        lang = max(probs, key=probs.get)
        total = sum(probs.values()) or 1.0
        return lang, probs[lang] / total

    def transcribe(self, audio: np.ndarray, language: str | None = None, hint_text: str | None = None) -> Transcript:
        t0 = time.perf_counter()
        with self._lock:
            if language in SUPPORTED_LANGS:
                lang, lang_p = language, 1.0
            else:
                lang, lang_p = self.detect_language(audio)
            # The initial prompt biases spelling of names/terms seen on screen and nudges Whisper to
            # keep digits and punctuation (which our completeness check relies on).
            prompt = {"en": "Quiz question. Is it 1990, 2,500 km, or 3.14?",
                      "fr": "Question de quiz. Est-ce 1990, 2 500 km ou 3,14 ?",
                      "ar": "سؤال مسابقة. هل هو ١٩٩٠ أم ٢٥٠٠ كم؟"}[lang]
            if hint_text:
                prompt = hint_text[-200:] + " " + prompt
            segments, info = self.model.transcribe(
                audio, language=lang, task="transcribe", beam_size=5, vad_filter=False,
                condition_on_previous_text=False, initial_prompt=prompt, word_timestamps=False)
            segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        if segs:
            lp = float(np.mean([s.avg_logprob for s in segs]))
            nsp = float(np.mean([s.no_speech_prob for s in segs]))
            conf = float(np.clip(np.exp(lp) * (1 - 0.5 * nsp), 0, 1))
        else:
            conf = 0.0
        return Transcript(text=text, language=lang, language_prob=float(lang_p), confidence=conf,
                          duration_s=len(audio) / SAMPLE_RATE, elapsed_ms=int((time.perf_counter() - t0) * 1000))


_transcriber: Transcriber | None = None
_tlock = threading.Lock()


def get_transcriber(model_size: str = "small") -> Transcriber:
    global _transcriber
    with _tlock:
        if _transcriber is None or _transcriber.model_size != model_size:
            _transcriber = Transcriber(model_size)
        return _transcriber


INTRO_RE = re.compile(r"^(ok(ay)?|so|alright|right|well|next question|here('s| is) (a|the|your|another)\b.*question"
                      r"|((a|an|une|un|la|the) )?(\w+ )?(question|quiz)( (de|d'|du|sur|about|on|in|of) ?[\w' -]{0,30})?"
                      r"|question (number )?\w+|listen( carefully)?|voici (une|la) question.*|question suivante"
                      r"|bon|alors|السؤال( التالي)?.*|سؤال.*)[.,:!]?$", re.I)
CONTINUATION_WORDS = {"in", "on", "at", "of", "for", "from", "with", "by", "during", "before", "after", "and",
                      "or", "than", "between", "within", "en", "au", "aux", "à", "dans", "de", "du", "des", "pour",
                      "avec", "et", "ou", "entre", "sur", "في", "من", "على", "عن", "مع", "و", "أو", "بين"}
WHISPER_HALLUCINATIONS = {"thank you.", "thanks for watching!", "merci.", "sous-titrage st' 501",
                          "ترجمة نانسي قنقر", "you", "."}


@dataclass
class UtteranceAssembler:
    """Turns a stream of transcribed segments into complete questions.

    * Incomplete speech ("Which planet has the ...") is held and joined with the next segment
      if it arrives within `join_window_s`.
    * Statements spoken just before a question ("A train leaves at 3 pm at 60 km/h.") are kept as
      part of the question when they carry content; intros ("Next question.") are dropped.
    * If held speech never completes it is flushed after `hold_timeout_s` as an *incomplete*
      observation (shown in the UI, never sent for analysis).
    """
    join_window_s: float = 4.0
    hold_timeout_s: float = 6.0
    context_window_s: float = 12.0
    pending_text: str = ""
    pending_t: float = 0.0
    pending_conf: list[float] = field(default_factory=list)
    pending_lang: str = "en"
    statements: deque = field(default_factory=lambda: deque(maxlen=3))

    grace_s: float = 1.0
    held: list = field(default_factory=list)
    held_t: float = 0.0

    @staticmethod
    def is_continuation(text: str, lang: str) -> bool:
        """'In Africa?' after 'Which river is the longest?' — a fragment completing the previous question."""
        words = text.split()
        if not words or len(words) > 8 or starts_like_question(text, lang):
            return False
        first = words[0].lower().strip(",.")
        return first in CONTINUATION_WORDS or text[0].islower()

    def add(self, tr: Transcript, now: float | None = None, more_coming: bool = False) -> list[Observation]:
        """Complete questions are held for `grace_s` (and while more speech is queued) so that a
        fragment spoken after a pause can still be attached to them."""
        now = time.monotonic() if now is None else now
        text = tr.text.strip()
        if not text or text.lower() in WHISPER_HALLUCINATIONS or tr.confidence < 0.15:
            return self.expire(now, more_coming)
        lang = tr.language or detect_language(text)
        if self.held and self.is_continuation(text, lang):
            last = self.held[-1]
            core = last.metadata["core_question"]
            frag = text[0].lower() + text[1:] if lang != "ar" else text
            new_core = core.rstrip("?؟ ").rstrip() + " " + frag
            if not new_core.endswith(("?", "؟")):
                new_core += "؟" if lang == "ar" else "?"
            last.text = last.text[: len(last.text) - len(core)] + new_core
            last.metadata["core_question"] = new_core
            last.metadata["joined_after_pause"] = True
            self.held_t = now
            return self.expire(now, more_coming)
        released = self.held
        self.held = []
        new = self._process(text, tr, lang, now)
        if new:
            self.held, self.held_t = new, now
        return released + self.expire(now, more_coming)

    def _process(self, text: str, tr: Transcript, lang: str, now: float) -> list[Observation]:
        if self.pending_text and now - self.pending_t <= self.join_window_s:
            text = self.pending_text + " " + text
            confs = self.pending_conf + [tr.confidence]
        else:
            confs = [tr.confidence]
        self.pending_text = ""
        parsed = extract_questions(text, lang)
        out: list[Observation] = []
        complete = [q for q in parsed if q.complete]
        if complete:
            # context statements from earlier segments + preamble in this one
            stmts = [s for (t, s) in self.statements if now - t <= self.context_window_s]
            for q in complete:
                pre = " ".join(stmts + ([q.preamble] if q.preamble else [])).strip()
                pre_sents = [s for s in re.split(r"(?<=[.!])\s+", pre) if s and not INTRO_RE.match(s.strip())]
                full = (" ".join(pre_sents) + " " + q.text).strip() if pre_sents else q.text
                out.append(Observation(
                    text=full, modality=Modality.AUDIO, confidence=float(np.mean(confs)) * (0.6 + 0.4 * tr.language_prob),
                    language=lang, options=q.options, complete=True, origin="audio",
                    stream_key="audio", observed_at=now,
                    metadata={"core_question": q.text, "language_prob": round(tr.language_prob, 3),
                              "asr_ms": tr.elapsed_ms, "spoken_s": round(tr.duration_s, 2)}))
            self.statements.clear()
            trailing = [q for q in parsed if not q.complete and parsed.index(q) > parsed.index(complete[-1])]
            if trailing:
                self._hold(trailing[-1].text, confs, lang, now)
            return out
        incomplete = [q for q in parsed if not q.complete]
        if incomplete or looks_incomplete(text, lang) or (starts_like_question(text, lang) and not text.endswith(".")):
            self._hold(text, confs, lang, now)
        else:
            self.statements.append((now, text))      # plain statement: keep as context
        return out

    def _hold(self, text: str, confs: list[float], lang: str, now: float) -> None:
        self.pending_text, self.pending_conf, self.pending_lang, self.pending_t = text, confs, lang, now

    def expire(self, now: float | None = None, more_coming: bool = False) -> list[Observation]:
        now = time.monotonic() if now is None else now
        out: list[Observation] = []
        if self.held and not more_coming and now - self.held_t >= self.grace_s:
            out, self.held = self.held, []
            for o in out:
                o.observed_at = now
        return out + self._expire_pending(now)

    def _expire_pending(self, now: float) -> list[Observation]:
        if self.pending_text and now - self.pending_t > self.hold_timeout_s:
            text, self.pending_text = self.pending_text, ""
            return [Observation(text=text, modality=Modality.AUDIO, confidence=float(np.mean(self.pending_conf)) * 0.5,
                                language=self.pending_lang, complete=False, origin="audio", stream_key="audio",
                                observed_at=now, metadata={"core_question": text, "reason": "speech ended mid-question"})]
        return []


def pcm16_from_float(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes()


def load_audio_file(path: str) -> np.ndarray:
    """Decode any audio file to 16 kHz mono float32 (PyAV, bundled with faster-whisper)."""
    from faster_whisper.audio import decode_audio
    return decode_audio(path, sampling_rate=SAMPLE_RATE)
