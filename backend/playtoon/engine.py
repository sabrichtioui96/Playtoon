"""Asynchronous orchestration: modality workers -> QuestionManager -> answer workers -> WebSocket push."""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .audio import AudioSegmenter, UtteranceAssembler, get_transcriber, pcm16_from_float
from .chat import ChatTracker
from .fusion import FusionConfig, QuestionManager
from .models import DetectedQuestion, Modality, Observation, Status, utc_now_iso
from .reasoning import ReasoningConfig, make_answerer
from .vision import VideoStreamProcessor, decode_image, iter_video, observations_from_text, process_image

log = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    asr_model: str = "small"
    language: str = "auto"                 # auto | en | fr | ar  (audio language preference)
    answer_workers: int = 2
    max_audio_wait_s: float = 5.0           # hold visual-only questions while speech is being transcribed
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)

    def public(self) -> dict[str, Any]:
        return {"asr_model": self.asr_model, "language": self.language,
                "reasoning": asdict(self.reasoning), "fusion": asdict(self.fusion)}


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
            t = asyncio.create_task(self._transcribe(ev.audio))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    async def _transcribe(self, audio: np.ndarray) -> None:
        try:
            async with self._lock:               # keep segment order
                lang = None if self.language == "auto" else self.language
                hint = self.engine.recent_visual_text()
                tr = await self.engine.run_cpu(get_transcriber(self.engine.cfg.asr_model).transcribe, audio, lang, hint)
                await self.engine.broadcast("transcript.final", {
                    "session": self.id, "text": tr.text, "language": tr.language,
                    "language_prob": round(tr.language_prob, 3), "confidence": round(tr.confidence, 3),
                    "duration_s": round(tr.duration_s, 2), "asr_ms": tr.elapsed_ms, "source": self.label})
                obs = self.assembler.add(tr, more_coming=self.in_speech or self.pending > 1)
                for o in obs:
                    o.origin = f"audio:{self.label}"
                await self.engine.ingest(obs)
        except Exception:
            log.exception("transcription failed")
        finally:
            self.pending -= 1

    async def finish(self) -> None:
        for ev in self.segmenter.flush():
            await self._handle(ev)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        held = self.assembler.expire(time.monotonic() + 3600)   # stream ended: release held questions
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
        while True:
            await self._frame_event.wait()
            self._frame_event.clear()
            for sid in list(self._latest_frame):
                data, t = self._latest_frame.pop(sid)
                proc = self.video_streams.setdefault(sid, VideoStreamProcessor(sid))
                idx[sid] = idx.get(sid, 0) + 1
                try:
                    frame = decode_image(data)
                    obs = await self.run_cpu(proc.process_frame, frame, idx[sid], t, "screen")
                    await self.ingest(obs)
                except Exception:
                    log.exception("frame processing failed")

    async def process_video_file(self, path: str, job_id: str, sample_fps: float = 5.0, realtime: bool = False) -> dict:
        proc = VideoStreamProcessor(job_id)
        self.jobs[job_id] = {"status": "running", "stats": proc.stats.to_dict()}
        start = time.monotonic()
        try:
            def frames():
                return list(iter_video(path, sample_fps))
            for fidx, t, frame in await self.run_cpu(frames):
                if realtime:
                    delay = start + t - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                obs = await self.run_cpu(proc.process_frame, frame, fidx, t, "video")
                for o in obs:
                    o.observed_at = time.monotonic()
                await self.ingest(obs)
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
        audio_busy = any(s.busy for s in self.audio_sessions.values())
        visual_only = all(m.family == "visual" for m in q.modalities)
        return audio_busy and visual_only and (now - q.first_seen) < self.cfg.max_audio_wait_s

    async def _scheduler(self) -> None:
        while True:
            await asyncio.sleep(0.1)
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
                ans = await self.answerer.answer(q)
                if q.revision != rev:          # superseded while we were waiting on the model
                    continue
                q.answer = ans
                q.status = Status.ANSWERED
            except Exception as e:
                log.exception("answering failed")
                q.status = Status.FAILED
                q.answer = None
                await self.broadcast("question.failed", {**q.to_dict(), "error": str(e)})
                continue
            q.detected_to_answer_ms = int((time.monotonic() - q.first_seen) * 1000)
            await self.broadcast("question.answered", q.to_dict())
            log.info("answered %s (%s) in %d ms total", q.question_id, q.question_text[:60], q.detected_to_answer_ms)

    async def reset(self) -> None:
        """Clear question history and conversation state (app "clear history" / test isolation)."""
        async with self._mlock:
            self.manager = QuestionManager(self.cfg.fusion)
            self.chat = ChatTracker()
            self.video_streams.clear()
            while not self._queue.empty():
                self._queue.get_nowait()
        await self.broadcast("reset", {})

    def stats(self) -> dict:
        qs = list(self.manager.questions.values())
        return {"questions": len(qs), "ai_requests": self.manager.ai_requests,
                "suppressed_duplicates": self.manager.suppressed_duplicates,
                "by_status": {s.value: sum(q.status == s for q in qs) for s in Status},
                "clients": len(self.clients), "audio_sessions": len(self.audio_sessions),
                "answerer": self.answerer.name, "capture": self.capture,
                "video_streams": {k: v.stats.to_dict() for k, v in self.video_streams.items()}}


__all__ = ["Engine", "EngineConfig", "AudioSession", "pcm16_from_float"]
