"""HTTP + WebSocket API.

  WS   /ws/client         server -> app event stream (question.*, transcript.*, capture.status ...)
  WS   /ws/audio          app -> server PCM16 16 kHz mono binary frames (authorised mic capture)
  POST /ingest/image      screenshot / image upload (manual import, OCR)
  POST /ingest/frame      screen-capture frame (MediaProjection); latest-frame-wins back-pressure
  POST /ingest/video      video file (frame-change detection + OCR), async job
  POST /ingest/browser    DOM text blocks from the browser extension
  POST /ingest/chat       chatbot message (streaming updates share message_id)
  POST /ingest/audio      audio file (wav/mp3/m4a...) through the same VAD/ASR pipeline
  GET  /questions  /questions/{id}  /stats  /config   PUT /config
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .audio import SAMPLE_RATE, load_audio_file, pcm16_from_float
from .engine import AudioSession, Engine, EngineConfig
from .models import Modality

log = logging.getLogger("playtoon")

engine: Engine | None = None


def build_config() -> EngineConfig:
    cfg = EngineConfig()
    cfg.asr_model = os.environ.get("PLAYTOON_ASR_MODEL", cfg.asr_model)
    cfg.reasoning.provider = os.environ.get("PLAYTOON_AI_PROVIDER", cfg.reasoning.provider)
    cfg.reasoning.model = os.environ.get("PLAYTOON_AI_MODEL", cfg.reasoning.model)
    cfg.reasoning.effort = os.environ.get("PLAYTOON_AI_EFFORT", cfg.reasoning.effort)
    return cfg


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    engine = Engine(build_config())
    if os.environ.get("PLAYTOON_WARMUP", "1") == "1":
        await asyncio.get_running_loop().run_in_executor(None, engine.warm_up)
    await engine.start()
    yield
    await engine.stop()


app = FastAPI(title="Playtoon multimodal question engine", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def E() -> Engine:
    assert engine is not None
    return engine


class BrowserBlock(BaseModel):
    id: str | None = None
    text: str


class BrowserPayload(BaseModel):
    page_id: str
    url: str = ""
    title: str = ""
    blocks: list[BrowserBlock]


class ChatPayload(BaseModel):
    conversation_id: str
    message_id: str
    role: str = "assistant"
    text: str
    final: bool = True


class TextPayload(BaseModel):
    text: str
    source: str = "manual"


class ConfigPayload(BaseModel):
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    language: str | None = None
    translate_to: str | None = None


@app.get("/health")
async def health():
    return {"ok": True, "answerer": E().answerer.name}


@app.get("/stats")
async def stats():
    return E().stats()


@app.get("/config")
async def get_config():
    return E().cfg.public()


@app.put("/config")
async def put_config(p: ConfigPayload):
    eng = E()
    eng.set_reasoning(provider=p.provider, model=p.model, effort=p.effort, translate_to=p.translate_to)
    if p.language in ("auto", "en", "fr", "ar"):
        eng.cfg.language = p.language
        for s in eng.audio_sessions.values():
            s.language = p.language
    await eng.broadcast("config", eng.cfg.public())
    return eng.cfg.public()


@app.post("/reset")
async def reset():
    await E().reset()
    return {"ok": True}


@app.get("/questions")
async def questions(limit: int = 100):
    return [q.to_dict() for q in E().manager.history(limit)]


@app.get("/questions/{qid}")
async def question(qid: str):
    q = E().manager.questions.get(qid)
    if not q:
        raise HTTPException(404)
    return q.to_dict()


@app.post("/ingest/image")
async def ingest_image(file: UploadFile = File(...), origin: str = Form("screenshot"), lang: str | None = Form(None)):
    data = await file.read()
    try:
        return await E().ingest_image(data, origin=f"{origin}:{file.filename}", lang_hint=lang)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/ingest/frame", status_code=202)
async def ingest_frame(file: UploadFile = File(...), stream_id: str = Form("screen")):
    E().submit_frame(stream_id, await file.read())
    return {"accepted": True}


@app.post("/ingest/video", status_code=202)
async def ingest_video(background: BackgroundTasks, file: UploadFile = File(...), sample_fps: float = Form(5.0),
                       realtime: bool = Form(False)):
    suffix = os.path.splitext(file.filename or "v.mp4")[1] or ".mp4"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(await file.read())
    job_id = "job_" + uuid.uuid4().hex[:8]

    async def run():
        try:
            await E().process_video_file(path, job_id, sample_fps, realtime)
        finally:
            os.unlink(path)
    background.add_task(run)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def job(job_id: str):
    j = E().jobs.get(job_id)
    if j is None:
        raise HTTPException(404)
    return j


@app.post("/ingest/browser")
async def ingest_browser(p: BrowserPayload):
    text = "\n".join(b.text for b in p.blocks if b.text.strip())
    qs = await E().ingest_text(text, Modality.BROWSER, f"browser:{p.url or p.page_id}", f"browser:{p.page_id}")
    return {"question_ids": sorted({q.question_id for q in qs})}


@app.post("/ingest/chat")
async def ingest_chat(p: ChatPayload):
    qs = await E().ingest_chat(p.conversation_id, p.message_id, p.role, p.text, p.final)
    return {"question_ids": sorted({q.question_id for q in qs})}


@app.post("/ingest/text")
async def ingest_text(p: TextPayload):
    qs = await E().ingest_text(p.text, Modality.VISUAL, p.source, None)
    return {"question_ids": sorted({q.question_id for q in qs})}


@app.post("/ingest/audio")
async def ingest_audio(file: UploadFile = File(...), language: str = Form("auto")):
    eng = E()
    suffix = os.path.splitext(file.filename or "a.wav")[1] or ".wav"
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(await file.read())
    try:
        audio = await eng.run_cpu(load_audio_file, path)
    finally:
        os.unlink(path)
    s = AudioSession(eng, language, label=f"file:{file.filename}")
    eng.audio_sessions[s.id] = s
    try:
        pcm = pcm16_from_float(audio)
        step = SAMPLE_RATE * 2 // 10
        for i in range(0, len(pcm), step):
            await s.feed(pcm[i:i + step])
        await s.feed(b"\x00" * SAMPLE_RATE * 2)   # 1 s of trailing silence closes the last utterance
        await s.finish()
    finally:
        eng.audio_sessions.pop(s.id, None)
    return {"session": s.id, "duration_s": round(len(audio) / SAMPLE_RATE, 2)}


@app.websocket("/ws/client")
async def ws_client(ws: WebSocket):
    await ws.accept()
    eng = E()
    eng.clients.add(ws)
    await ws.send_text(json.dumps({"type": "hello", "data": {
        "answerer": eng.answerer.name, "config": eng.cfg.public(), "capture": eng.capture,
        "history": [q.to_dict() for q in eng.manager.history(50)]}}, ensure_ascii=False))
    try:
        while True:
            msg = await ws.receive_text()
            try:
                m = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if m.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            elif m.get("type") == "capture":
                # The app reports OS-level capture state (screen capture via MediaProjection) for indicators
                await eng.set_capture(m.get("key", "screen"), bool(m.get("active")), device=m.get("device", "android"))
    except WebSocketDisconnect:
        pass
    finally:
        eng.clients.discard(ws)


@app.websocket("/ws/audio")
async def ws_audio(ws: WebSocket, language: str = "auto", device: str = "android"):
    """Binary messages: raw PCM16LE mono 16 kHz. Text messages: {"type":"stop"}."""
    await ws.accept()
    eng = E()
    s = AudioSession(eng, language if language != "auto" else eng.cfg.language, label=f"mic:{device}")
    eng.audio_sessions[s.id] = s
    await eng.set_capture(f"microphone:{s.id}", True, device=device)
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await s.feed(msg["bytes"])
            elif msg.get("text"):
                if json.loads(msg["text"]).get("type") == "stop":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        await s.finish()
        eng.audio_sessions.pop(s.id, None)
        await eng.set_capture(f"microphone:{s.id}", False)
        try:
            await ws.close()
        except Exception:
            pass


def main() -> None:
    import uvicorn
    uvicorn.run("playtoon.server:app", host=os.environ.get("PLAYTOON_HOST", "0.0.0.0"),
                port=int(os.environ.get("PLAYTOON_PORT", "8765")), log_level="info")


if __name__ == "__main__":
    main()
