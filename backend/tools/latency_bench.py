"""End-to-end latency benchmark: time from a question being shown / finished being spoken to the
answer arriving on the WebSocket the app listens to.

Starts its own server (offline answerer unless PLAYTOON_AI_PROVIDER says otherwise, so the numbers
isolate Playtoon's pipeline from model latency), runs each scenario N times, prints and saves
median / p90 per modality to docs/latency.json."""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
import conftest  # noqa: E402  (server bootstrap + event log)

FIX = conftest.FIX
DOCS = conftest.ROOT.parent / "docs"


def wait_answer(ev, t_from: float, timeout=60.0, need_source: str | None = None) -> float | None:
    end = time.time() + timeout
    while time.time() < end:
        for e in ev.events:
            if e["type"] == "question.answered" and e["_t"] >= t_from and (
                    need_source is None or need_source in e["data"]["source"]):
                return e["_t"] - t_from
        time.sleep(0.02)
    return None


class TimedEventLog(conftest.EventLog):
    async def _run(self):
        async with websockets.connect(self.url, max_size=None) as ws:
            self._ready.set()
            while not self._stop:
                try:
                    msg = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    continue
                e = json.loads(msg)
                e["_t"] = time.time()
                self.events.append(e)


def stream_realtime(base: str, path: Path) -> float:
    """Stream at real-time speed; return wall time at which the speech ended (start of trailing pad)."""
    with wave.open(str(path)) as w:
        pcm = w.readframes(w.getnframes())
    samples = len(pcm) // 2
    import numpy as np
    a = np.frombuffer(pcm, np.int16)
    voiced = np.flatnonzero(np.abs(a) > 800)
    speech_end_s = (voiced[-1] / 16000) if voiced.size else samples / 16000
    t_end = {}

    async def run():
        url = base.replace("http", "ws") + "/ws/audio?language=auto&device=bench"
        async with websockets.connect(url, max_size=None) as ws:
            t0 = time.time()
            step = 3200
            for i in range(0, len(pcm), step):
                target = t0 + i / 2 / 16000
                if (d := target - time.time()) > 0:
                    await asyncio.sleep(d)
                await ws.send(pcm[i:i + step])
            t_end["t"] = t0 + speech_end_s
            await asyncio.sleep(8)              # keep the mic "open" like a real session
            await ws.send(json.dumps({"type": "stop"}))
            try:
                await asyncio.wait_for(ws.recv(), 30)
            except Exception:
                pass
    asyncio.run(run())
    return t_end["t"]


def main(runs: int = 3) -> None:
    gen = conftest.run_server()
    base = next(gen)
    ev = TimedEventLog(base)
    c = httpx.Client(base_url=base, timeout=120)
    res: dict[str, list[float]] = {}

    def run(name, fn, need_source=None):
        for _ in range(runs):
            c.post("/reset")
            time.sleep(0.5)
            ev.events.clear()
            t_from = fn()
            dt = wait_answer(ev, t_from, need_source=need_source)
            res.setdefault(name, []).append(round(dt, 3) if dt is not None else float("nan"))
            print(name, res[name][-1], flush=True)

    blocks = [{"text": "Which planet has the largest number of moons?"}, {"text": "A) Jupiter"}, {"text": "B) Saturn"},
              {"text": "C) Uranus"}, {"text": "D) Neptune"}]

    def browser():
        t = time.time()
        c.post("/ingest/browser", json={"page_id": "bench", "blocks": blocks})
        return t

    def chat():
        t = time.time()
        c.post("/ingest/chat", json={"conversation_id": "b", "message_id": "1", "role": "assistant",
                                     "text": "What is the capital of Japan? A) Kyoto B) Osaka C) Tokyo D) Nagoya"})
        return t

    png = (FIX / "image_question.png").read_bytes()

    def image():
        t = time.time()
        c.post("/ingest/image", files={"file": ("q.png", png, "image/png")})
        return t

    run("browser_text", browser)
    run("chat_message", chat)
    run("image_upload", image)
    for lang in ("en", "fr"):
        run(f"speech_{lang}", lambda lang=lang: stream_realtime(base, FIX / f"audio_{lang}.wav"), need_source="audio")

    summary = {k: {"median_s": round(statistics.median([x for x in v if x == x]), 3) if any(x == x for x in v) else None,
                   "max_s": max(v), "runs": v} for k, v in res.items()}
    print(json.dumps(summary, indent=1))
    DOCS.mkdir(exist_ok=True)
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    out = DOCS / "latency.json"
    data = json.loads(out.read_text()) if out.exists() else {}
    data[label] = summary
    out.write_text(json.dumps(data, indent=1))
    ev.close()
    try:
        next(gen)
    except StopIteration:
        pass


if __name__ == "__main__":
    main()
