"""Acceptance-test harness: starts the real server (uvicorn subprocess), records every WebSocket
event the Android app would receive, and writes per-test evidence to docs/acceptance_results.json."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import websockets

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
PORT = int(os.environ.get("PLAYTOON_TEST_PORT", "8799"))
BASE = f"http://127.0.0.1:{PORT}"
RESULTS_FILE = ROOT.parent / "docs" / "acceptance_results.json"
RESULTS: dict[str, dict] = {}


@pytest.fixture(scope="session")
def server():
    yield from run_server()


def run_server():
    """Start the real server as a subprocess; yields its base URL, terminates it afterwards."""
    env = {**os.environ, "PLAYTOON_PORT": str(PORT), "PLAYTOON_HOST": "127.0.0.1",
           "PLAYTOON_AI_PROVIDER": os.environ.get("PLAYTOON_AI_PROVIDER", "offline"),
           "PLAYTOON_ASR_MODEL_AR": os.environ.get("PLAYTOON_ASR_MODEL_AR", "large-v3-turbo"),
           "PYTHONIOENCODING": "utf-8"}
    log = open(ROOT / "tests" / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "playtoon.server"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            if httpx.get(BASE + "/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if proc.poll() is not None:
            raise RuntimeError("server exited; see tests/server.log")
        time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield BASE
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


class EventLog:
    """Background WebSocket client on /ws/client (what the Android app consumes)."""

    def __init__(self, base: str):
        self.url = base.replace("http", "ws") + "/ws/client"
        self.events: list[dict] = []
        self._stop = False
        self._ready = threading.Event()
        self._t = threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True)
        self._t.start()
        self._ready.wait(10)

    async def _run(self):
        async with websockets.connect(self.url, max_size=None) as ws:
            self._ready.set()
            while not self._stop:
                try:
                    msg = await asyncio.wait_for(ws.recv(), 0.5)
                except asyncio.TimeoutError:
                    continue
                self.events.append(json.loads(msg))

    def of(self, *types: str) -> list[dict]:
        return [e for e in self.events if e["type"] in types]

    def close(self):
        self._stop = True
        self._t.join(3)


@pytest.fixture
def client(server):
    with httpx.Client(base_url=server, timeout=600) as c:
        c.post("/reset")
        yield c


@pytest.fixture
def events(server):
    ev = EventLog(server)
    yield ev
    ev.close()


def wait_for(pred, timeout=60.0, interval=0.25):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    return pred()


def record(test_id: str, **evidence):
    RESULTS[test_id] = {**RESULTS.get(test_id, {}), **evidence}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        tid = item.name
        RESULTS.setdefault(tid, {})
        RESULTS[tid]["outcome"] = rep.outcome
        RESULTS[tid]["duration_s"] = round(rep.duration, 2)
        if rep.outcome != "passed":
            RESULTS[tid]["failure"] = str(rep.longrepr)[-1500:]


def pytest_sessionfinish(session, exitstatus):
    RESULTS_FILE.parent.mkdir(exist_ok=True)
    old = {}
    if RESULTS_FILE.exists():
        try:
            old = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    old.update(RESULTS)
    old["_meta"] = {"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "python": sys.version.split()[0]}
    RESULTS_FILE.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
