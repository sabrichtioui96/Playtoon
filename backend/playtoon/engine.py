"""Asynchronous orchestration: modality workers -> QuestionManager -> answer workers -> WebSocket push."""
from __future__ import annotations

import asyncio
import itertools
import json
import os
from pathlib import Path
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .audio import AudioSegmenter, UtteranceAssembler, get_transcriber, pcm16_from_float
from .text_utils import detect_language
from .chat import ChatTracker
from .fusion import FusionConfig, QuestionManager
from .models import Answer, DetectedQuestion, Modality, Observation, Status, utc_now_iso
from .reasoning import ReasoningConfig, make_answerer
from .vision import VideoStreamProcessor, decode_image, iter_video, observations_from_text, process_image

log = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    asr_model: str = "small"
    language: str = "auto"                 # auto | en | fr | ar  (audio language preference)
    asr_vocabulary: str = ""               # host-supplied topic terms that bias speech recognition spelling
    answer_workers: int = 2
    max_audio_wait_s: float = 1.0           # hold progressive visual-only questions while speech is transcribed
    speculative: bool | str = "paid_only"  # start the model during the settle window (paid providers only)
    speculative_delay_s: float = 0.25
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)

    def public(self) -> dict[str, Any]:
        return {"asr_model": self.asr_model, "language": self.language, "asr_vocabulary": self.asr_vocabulary,
                "reasoning": asdict(self.reasoning), "fusion": asdict(self.fusion)}


class AnswerCache:
    """Answers already obtained for a question (same text, options, context, language). Persisted to
    data/answer_cache.json so a question repeated in a later game costs no API call."""

    def __init__(self, path: Path | None = None, max_items: int = 5000):
        self.path = path or Path(os.environ.get("PLAYTOON_CACHE", Path(__file__).resolve().parents[1] / "data" / "answer_cache.json"))
        self.max_items = max_items
        self.items: dict[str, dict] = {}
        try:
            self.items = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    def get(self, key: str) -> dict | None:
        return self.items.get(key)

    def put(self, key: str, value: dict) -> None:
        self.items[key] = value
        while len(self.items) > self.max_items:
            self.items.pop(next(iter(self.items)))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.warning("could not persist answer cache")


class AudioSession:
    _ids = itertools.count(1)

    def __init__(self, engine: "Engine", language: str = "auto", label: str = "microphone"):
        self.id = f"audio{next(self._ids)}"
        self.engine = engine
        self.language = language
        self.label = label
        self.segmenter = AudioSegmenter()
        self.assembler = UtteranceAssembler()
        self.in_speech = False
        self.pending = 0
        self.sticky_lang: str | None = None
        self.sticky_prob = 0.0
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.started = time.monotonic()

    @property
    def busy(self) -> bool:
        return self.in_speech or self.pending > 0 or bool(self.assembler.held)

    async def feed(self, pcm: bytes) -> None:
        for ev in self.segmenter.feed(pcm):
            await self._handle(ev)

    async def _handle(self, ev) -> None:
        if ev.kind == "speech_start":
            self.in_speech = True
            await self.engine.broadcast("audio.speech_start", {"session": self.id, "t": round(ev.start_s, 2)})
        elif ev.kind == "segment":
            self.in_speech = False
            self.pending += 1
            t = asyncio.create_task(self._transcribe(ev.audio, time.monotonic()))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    async def _transcribe(self, audio: np.ndarray, segment_end: float) -> None:
        try:
            async with self._lock:               # keep segment order
                tr = await self._transcribe_fast(audio)
                await self.engine.broadcast("transcript.final", {
                    "session": self.id, "text": tr.text, "language": tr.language,
                    "language_prob": round(tr.language_prob, 3), "confidence": round(tr.confidence, 3),
                    "duration_s": round(tr.duration_s, 2), "asr_ms": tr.elapsed_ms, "source": self.label})
                obs = self.assembler.add(tr, more_coming=self.in_speech or self.pending > 1,
                                         segment_end=segment_end)
                for o in obs:
                    o.origin = f"audio:{self.label}"
                await self.engine.ingest(obs)
        except Exception:
            log.exception("transcription failed")
        finally:
            self.pending -= 1

    async def _transcribe_fast(self, audio: np.ndarray):
        """Language detection costs a second full Whisper encoder pass (~1.6 s on CPU). Once a
        session has confidently detected its language, later segments reuse it; detection runs
        again only if the result looks wrong (low confidence or the text reads as another language)."""
        tx = get_transcriber(self.engine.cfg.asr_model)
        hint = " ".join(x for x in (self.engine.cfg.asr_vocabulary, self.engine.recent_visual_text()) if x) or None
        if self.language != "auto":
            return await self.engine.run_cpu(tx.transcribe, audio, self.language, hint)
        if self.sticky_lang:
            tr = await self.engine.run_cpu(tx.transcribe, audio, self.sticky_lang, hint)
            text_lang = detect_language(tr.text) if len(tr.text.split()) >= 4 else self.sticky_lang
            if tr.confidence >= 0.45 and text_lang in (self.sticky_lang, "und"):
                tr.language_prob = self.sticky_prob
                return tr
            self.sticky_lang = None              # language changed or poor result: detect again
        tr = await self.engine.run_cpu(tx.transcribe, audio, None, hint)
        if tr.language_prob >= 0.9 and tr.confidence >= 0.45:
            self.sticky_lang, self.sticky_prob = tr.language, tr.language_prob
        return tr

    async def finish(self) -> None:
        for ev in self.segmenter.flush():
            await self._handle(ev)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        held = self.assembler.release_all()                      # stream ended: release held questions
        for o in held:
            o.origin = f"audio:{self.label}"
        await self.engine.ingest(held)


class Engine:
    def __init__(self, cfg: EngineConfig | None = None):
        self.cfg = cfg or EngineConfig()
        self.manager = QuestionManager(self.cfg.fusion)
        self.chat = ChatTracker()
        self.answerer = make_answerer(self.cfg.reasoning)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="playtoon-cpu")
        self.clients: set[Any] = set()
        self.audio_sessions: dict[str, AudioSession] = {}
        self.video_streams: dict[str, VideoStreamProcessor] = {}
        self._latest_frame: dict[str, tuple[bytes, float]] = {}
        self._frame_event = asyncio.Event()
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._tasks: list[asyncio.Task] = []
        self._mlock = asyncio.Lock()
        self.jobs: dict[str, dict] = {}
        self.capture: dict[str, dict] = {}        # active capture indicators (privacy)
        self._spec: dict[str, tuple] = {}
        self.model_calls = self.spec_started = self.spec_used = 0
        self.cache_hits = 0
        self.answer_cache = AnswerCache()

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._scheduler(), name="scheduler"),
                       asyncio.create_task(self._frame_worker(), name="frames")]
        for i in range(self.cfg.answer_workers):
            self._tasks.append(asyncio.create_task(self._answer_worker(i), name=f"answer{i}"))
        log.info("engine started; answerer=%s", self.answerer.name)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.pool.shutdown(wait=False, cancel_futures=True)

    def warm_up(self) -> None:
        from .ocr import get_engine
        get_engine()
        get_transcriber(self.cfg.asr_model)

    async def run_cpu(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *args)

    def set_reasoning(self, **kw) -> None:
        for k, v in kw.items():
            if k in ("model", "provider", "effort") and v == "":
                continue                         # empty = keep the server's setting / provider default
            if hasattr(self.cfg.reasoning, k) and v is not None:
                setattr(self.cfg.reasoning, k, v)
        self.answerer = make_answerer(self.cfg.reasoning)

    # ---------------------------------------------------------------- broadcast
    async def broadcast(self, typ: str, data: Any) -> None:
        msg = json.dumps({"type": typ, "ts": utc_now_iso(), "data": data}, ensure_ascii=False)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def set_capture(self, key: str, active: bool, **info) -> None:
        if active:
            self.capture[key] = {"since": utc_now_iso(), **info}
        else:
            self.capture.pop(key, None)
        await self.broadcast("capture.status", {"active": self.capture})

    # ---------------------------------------------------------------- ingestion
    async def ingest(self, observations: list[Observation]) -> list[DetectedQuestion]:
        touched = []
        async with self._mlock:
            for o in observations:
                for ev, q in self.manager.ingest(o):
                    touched.append(q)
                    if ev != "question.duplicate":
                        await self.broadcast(ev, q.to_dict())
            for q in {id(x): x for x in touched}.values():
                self._speculate(q)
        return touched

    async def ingest_image(self, data: bytes, origin: str = "image", lang_hint: str | None = None) -> dict:
        img = decode_image(data)
        text, obs = await self.run_cpu(process_image, img, origin, lang_hint)
        qs = await self.ingest(obs)
        return {"ocr_text": text, "question_ids": sorted({q.question_id for q in qs})}

    async def ingest_text(self, text: str, modality: Modality, origin: str, stream_key: str | None,
                          confidence: float = 0.99) -> list[DetectedQuestion]:
        return await self.ingest(observations_from_text(text, confidence, origin, stream_key, modality))

    async def ingest_chat(self, conversation_id: str, message_id: str, role: str, text: str, final: bool) -> list[DetectedQuestion]:
        return await self.ingest(self.chat.ingest(conversation_id, message_id, role, text, final))

    def submit_frame(self, stream_id: str, data: bytes) -> None:
        """Screen-capture frames: only the newest frame per stream is kept (back-pressure)."""
        self._latest_frame[stream_id] = (data, time.monotonic())
        self._frame_event.set()

    async def _frame_worker(self) -> None:
        idx: dict[str, int] = {}
        last: dict[str, object] = {}
        while True:
            try:
                await asyncio.wait_for(self._frame_event.wait(), 1.0)
            except asyncio.TimeoutError:
                # Clients only send frames that changed, so the settled end state of an animation may
                # be the last frame we get: flush streams that went quiet while still "in motion".
                for sid, frame in list(last.items()):
                    proc = self.video_streams.get(sid)
                    if proc is not None:
                        try:
                            await self.ingest(await self.run_cpu(proc.flush, frame, idx[sid], time.monotonic(), "screen"))
                        except Exception:
                            log.exception("frame flush failed")
                    last.pop(sid, None)
                continue
            self._frame_event.clear()
            for sid in list(self._latest_frame):
                data, t = self._latest_frame.pop(sid)
                proc = self.video_streams.setdefault(sid, VideoStreamProcessor(sid))
                idx[sid] = idx.get(sid, 0) + 1
                try:
                    frame = decode_image(data)
                    last[sid] = frame
                    obs = await self.run_cpu(proc.process_frame, frame, idx[sid], t, "screen")
                    await self.ingest(obs)
                except Exception:
                    log.exception("frame processing failed")

    async def process_video_file(self, path: str, job_id: str, sample_fps: float = 5.0, realtime: bool = False) -> dict:
        proc = VideoStreamProcessor(job_id)
        self.jobs[job_id] = {"status": "running", "stats": proc.stats.to_dict()}
        start = time.monotonic()
        try:
            gen = iter_video(path, sample_fps)          # decoded lazily, one sampled frame at a time
            last = None
            while (item := await self.run_cpu(next, gen, None)) is not None:
                fidx, t, frame = item
                last = item
                if realtime:
                    delay = start + t - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                obs = await self.run_cpu(proc.process_frame, frame, fidx, t, "video")
                for o in obs:
                    o.observed_at = time.monotonic()
                await self.ingest(obs)
            if last is not None:
                await self.ingest(await self.run_cpu(proc.flush, last[2], last[0], last[1] + 0.01, "video"))
            self.jobs[job_id] = {"status": "done", "stats": proc.stats.to_dict()}
        except Exception as e:
            log.exception("video job failed")
            self.jobs[job_id] = {"status": "failed", "error": str(e), "stats": proc.stats.to_dict()}
        await self.broadcast("job.done", {"job_id": job_id, **self.jobs[job_id]})
        return self.jobs[job_id]

    def recent_visual_text(self, window_s: float = 30.0) -> str | None:
        now = time.monotonic()
        recent = [q for q in self.manager.questions.values()
                  if now - q.last_seen < window_s and any(m.family == "visual" for m in q.modalities)]
        if not recent:
            return None
        q = max(recent, key=lambda q: q.last_seen)
        return q.question_text + (" " + ", ".join(q.options) if q.options else "")

    # ---------------------------------------------------------------- scheduling & answering
    def _hold(self, q: DetectedQuestion, now: float) -> bool:
        """Briefly delay a progressive on-screen question while speech is being transcribed, so a
        spoken copy can merge first. Final content is never held: if the spoken copy arrives after
        the answer, it merges without a second request."""
        if self.manager.is_final(q):
            return False
        audio_busy = any(s.busy for s in self.audio_sessions.values())
        visual_only = all(m.family == "visual" for m in q.modalities)
        return audio_busy and visual_only and (now - q.first_seen) < self.cfg.max_audio_wait_s

    # ---- speculative answering: start the model while the settle window is still open
    def _speculate(self, q: DetectedQuestion) -> None:
        if not self.cfg.speculative or q.status != Status.SETTLING or self.manager.is_final(q):
            return
        if self.cfg.speculative == "paid_only" and self.answerer.name not in ("anthropic", "xai"):
            return            # free tiers (Groq): never spend quota on a call that might be discarded
        if self.answer_cache.get(self._cache_key(q)) is not None:
            return
        fp = self.manager.fingerprint(q)
        cur = self._spec.get(q.question_id)
        if cur is not None:
            if cur[0] == fp:
                return
            cur[1].cancel()
        self._spec[q.question_id] = (fp, asyncio.create_task(self._spec_run(q, fp)))

    async def _spec_run(self, q: DetectedQuestion, fp: tuple):
        await asyncio.sleep(self.cfg.speculative_delay_s)      # debounce rapidly changing text
        if self.manager.fingerprint(q) != fp:
            return None
        self.model_calls += 1
        self.spec_started += 1
        return await self.answerer.answer(q)

    def _cache_key(self, q: DetectedQuestion) -> str:
        text, opts, _, ctx = self.manager.fingerprint(q)
        return json.dumps([q.language, text, list(opts), list(ctx), self.cfg.reasoning.translate_to or ""],
                          ensure_ascii=False)

    async def _get_answer(self, q: DetectedQuestion):
        key = self._cache_key(q)
        hit = self.answer_cache.get(key)
        if hit is not None:                       # same question seen before: no API call at all
            self.cache_hits += 1
            self._spec.pop(q.question_id, None)
            return Answer(hit["suggested_answer"], hit["option_index"], hit["confidence"], hit["explanation"],
                          f"{hit['provider']} (cached)", hit.get("model"), 0)
        ans = await self._get_answer_uncached(q)
        if ans.suggested_answer and ans.provider != "offline":
            self.answer_cache.put(key, ans.to_dict())
        return ans

    async def _get_answer_uncached(self, q: DetectedQuestion):
        spec = self._spec.pop(q.question_id, None)
        if spec is not None:
            fp, task = spec
            if fp == self.manager.fingerprint(q):
                try:
                    ans = await task
                except (asyncio.CancelledError, Exception):
                    ans = None
                if ans is not None:
                    self.spec_used += 1
                    return ans
            else:
                task.cancel()
        self.model_calls += 1
        return await self.answerer.answer(q)

    async def _scheduler(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            now = time.monotonic()
            async with self._mlock:
                ready = self.manager.due(now, hold=self._hold)
                for q in ready:
                    await self.broadcast("question.ready", q.to_dict())
                    prio = -(len(q.source) * 10 + (5 if q.options else 0) + q.confidence)
                    await self._queue.put((prio, next(self._seq), q.question_id, q.revision))
                for q in self.manager.expire(now):
                    await self.broadcast("question.updated", q.to_dict())
            for s in list(self.audio_sessions.values()):
                obs = s.assembler.expire(now, more_coming=s.in_speech or s.pending > 0)
                if obs:
                    await self.ingest(obs)

    async def _answer_worker(self, wid: int) -> None:
        while True:
            _, _, qid, rev = await self._queue.get()
            q = self.manager.questions.get(qid)
            if q is None or q.revision != rev or q.status != Status.READY:
                continue
            async with self._mlock:
                self.manager.mark_analyzing(q)
            await self.broadcast("question.analyzing", q.to_dict())
            t0 = time.monotonic()
            try:
                ans = await self._get_answer(q)
                if q.revision != rev:          # superseded while we were waiting on the model
                    continue
                q.answer = ans
                q.error = None
                q.status = Status.ANSWERED
            except Exception as e:
                log.exception("answering failed")
                q.status = Status.FAILED
                q.answer = None
                q.error = str(e)
                await self.broadcast("question.failed", q.to_dict())
                continue
            q.detected_to_answer_ms = int((time.monotonic() - q.first_seen) * 1000)
            await self.broadcast("question.answered", q.to_dict())
            log.info("answered %s (%s) in %d ms total", q.question_id, q.question_text[:60], q.detected_to_answer_ms)

    async def reset(self) -> None:
        """Clear question history and conversation state (app "clear history" / test isolation)."""
        async with self._mlock:
            for _, task in self._spec.values():
                task.cancel()
            self._spec.clear()
            self.model_calls = self.spec_started = self.spec_used = 0
            self.manager = QuestionManager(self.cfg.fusion)
            self.chat = ChatTracker()
            self.video_streams.clear()
            while not self._queue.empty():
                self._queue.get_nowait()
        await self.broadcast("reset", {})

    def stats(self) -> dict:
        qs = list(self.manager.questions.values())
        return {"questions": len(qs), "ai_requests": self.manager.ai_requests,
                "model_calls": self.model_calls, "speculative_started": self.spec_started,
                "speculative_used": self.spec_used, "cache_hits": self.cache_hits,
                "rate_limited": getattr(self.answerer, "rate_limited", 0),
                "suppressed_duplicates": self.manager.suppressed_duplicates,
                "by_status": {s.value: sum(q.status == s for q in qs) for s in Status},
                "clients": len(self.clients), "audio_sessions": len(self.audio_sessions),
                "answerer": self.answerer.name, "capture": self.capture,
                "video_streams": {k: v.stats.to_dict() for k, v in self.video_streams.items()}}


__all__ = ["Engine", "EngineConfig", "AudioSession", "pcm16_from_float"]
