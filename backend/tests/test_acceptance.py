"""The 10 acceptance tests from the Playtoon specification (section I), run against the real
server over HTTP/WebSocket exactly as the Android app and browser extension talk to it."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import wave

import httpx
import pytest
import websockets
from rapidfuzz import fuzz

from conftest import BASE, FIX, EventLog, record, wait_for
from playtoon.text_utils import normalize_for_match



# ----------------------------------------------------------------------------- helpers
def questions(c: httpx.Client) -> list[dict]:
    return c.get("/questions").json()


def find(c: httpx.Client, *keywords: str, status: str | None = None) -> dict | None:
    for q in questions(c):
        t = normalize_for_match(q["question_text"])
        if all(normalize_for_match(k) in t for k in keywords) and (status is None or q["status"] == status):
            return q
    return None


def answered(c, *kw, timeout=90):
    return wait_for(lambda: find(c, *kw, status="answered"), timeout)


def stream_wav(path, language="auto", speed=3.0, chunk_ms=100):
    """Stream a WAV file to /ws/audio as PCM16 16 kHz chunks (like the Android AudioRecord loop)."""
    with wave.open(str(path)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        pcm = w.readframes(w.getnframes())
    step = 16000 * 2 * chunk_ms // 1000

    async def run():
        url = BASE.replace("http", "ws") + f"/ws/audio?language={language}&device=test"
        async with websockets.connect(url, max_size=None) as ws:
            for i in range(0, len(pcm), step):
                await ws.send(pcm[i:i + step])
                await asyncio.sleep(chunk_ms / 1000 / speed)
            await ws.send(b"\x00" * 32000)
            await ws.send(json.dumps({"type": "stop"}))
            try:
                await asyncio.wait_for(ws.recv(), 120)     # server closes after finishing transcription
            except (websockets.ConnectionClosed, asyncio.TimeoutError):
                pass
    asyncio.run(run())


def transcripts(ev: EventLog) -> list[dict]:
    return [e["data"] for e in ev.of("transcript.final")]


def summary(q: dict) -> dict:
    a = q.get("answer") or {}
    return {k: q[k] for k in ("question_id", "question_text", "source", "channels", "language", "options",
                              "confidence", "status", "revision", "discrepancies", "processing_ms")} | {
        "answer": a.get("suggested_answer"), "option_index": a.get("option_index"), "answer_provider": a.get("provider")}


# ----------------------------------------------------------------------------- browser scenario (tests 1 & 4)
@pytest.fixture(scope="module")
def browser_run(server):
    from playwright.sync_api import sync_playwright
    with httpx.Client(base_url=server, timeout=600) as c:
        c.post("/reset")
        ev = EventLog(server)
        posts = []
        content_js = (FIX.parents[2] / "browser-extension" / "content.js").read_text(encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1100, "height": 700})

            def post(path, body):
                posts.append((path, json.loads(body)))
                c.post(path, content=body, headers={"Content-Type": "application/json"})
            page.expose_function("__playtoonPost", post)
            page.goto((FIX / "browser_quiz.html").as_uri())
            page.evaluate("window.__playtoonTransport = (p, b) => window.__playtoonPost(p, JSON.stringify(b))")
            page.add_script_tag(content=content_js)          # = extension popup "Read questions on this tab"
            page.evaluate("runScenario()")
            page.wait_for_function("window.scenarioDone === true", timeout=120000)
            time.sleep(2.5)
            shot = page.screenshot()
            browser.close()
        # Browser OCR path: the screenshot of the same page goes through OCR too
        ocr = c.post("/ingest/image", files={"file": ("browser.png", shot, "image/png")}, data={"origin": "browser-screenshot"}).json()
        wait_for(lambda: all(q["status"] in ("answered", "incomplete") for q in questions(c)), 60)
        time.sleep(1.5)
        snap = {"questions": questions(c), "stats": c.get("/stats").json(), "posts": posts, "ocr": ocr,
                "events": list(ev.events)}
        ev.close()
        (FIX.parent / "browser_screenshot.png").write_bytes(shot)
        return snap


def _bq(snap, *kw):
    for q in snap["questions"]:
        t = normalize_for_match(q["question_text"])
        if all(normalize_for_match(k) in t for k in kw):
            return q
    return None


def test_01_browser_text(browser_run):
    q = _bq(browser_run, "planet", "largest number of moons")
    assert q, "browser question not detected"
    assert q["options"] == ["Jupiter", "Saturn", "Uranus", "Neptune"]
    assert q["status"] == "answered" and q["answer"]["option_index"] == 1
    assert "browser" in q["channels"]
    # progressive typing produced fragments ("Which pl...") but only ONE question and ONE analysis
    page_qs = [x for x in browser_run["questions"] if any(c in x["channels"] for c in ("browser", "visual"))]
    planet_like = [x for x in page_qs if fuzz.partial_ratio("which planet has the largest number of moons", normalize_for_match(x["question_text"])) > 80]
    assert len(planet_like) == 1, [x["question_text"] for x in planet_like]
    # the screenshot OCR of the same page merged into the same question (no second AI request)
    assert "visual" in q["channels"]
    assert q["revision"] <= 1
    # content in <input> fields is never read
    assert not any("password" in json.dumps(b).lower() for _, b in browser_run["posts"])
    page_posts = [b for p, b in browser_run["posts"] if p == "/ingest/browser"]
    record("test_01_browser_text", question=summary(q), dom_updates_sent=len(page_posts),
           screenshot_ocr=browser_run["ocr"]["ocr_text"])


def test_04_chatbot_conversation(browser_run):
    hamlet = _bq(browser_run, "who wrote hamlet")
    born = _bq(browser_run, "which country was he born")
    japan = _bq(browser_run, "capital of japan")
    aus = _bq(browser_run, "what about australia")
    assert hamlet and born and japan and aus, [x["question_text"] for x in browser_run["questions"]]
    assert all("chat" in x["channels"] for x in (hamlet, born, japan, aus))
    # two consecutive questions in one message -> two questions
    assert hamlet["question_id"] != born["question_id"]
    # inline multiple-choice options parsed from the chat message
    assert japan["options"] == ["Kyoto", "Osaka", "Tokyo", "Nagoya"] and japan["answer"]["option_index"] == 2
    # context-dependent follow-up carries the conversation context and is answered with it
    assert any("japan" in c.lower() for c in aus["context"])
    assert aus["answer"]["suggested_answer"] == "Canberra"
    # greetings / statements and the user's own messages are not questions
    texts = " ".join(x["question_text"] for x in browser_run["questions"]).lower()
    assert "quizbot" not in texts and "shakespeare, england" not in texts
    chat_qs = [x for x in browser_run["questions"] if "chat" in x["channels"] and x["status"] == "answered"]
    assert len(chat_qs) == 4, [x["question_text"] for x in chat_qs]
    record("test_04_chatbot_conversation", questions=[summary(x) for x in (hamlet, born, japan, aus)],
           ai_requests_total=browser_run["stats"]["ai_requests"])


# ----------------------------------------------------------------------------- image & video
def test_02_image_question(client, events):
    r = client.post("/ingest/image", files={"file": ("image_question.png", (FIX / "image_question.png").read_bytes(), "image/png")}).json()
    q = answered(client, "planet", "moons")
    assert q and q["source"] == ["visual"]
    assert q["options"] == ["Jupiter", "Saturn", "Uranus", "Neptune"]
    assert q["answer"]["option_index"] == 1
    m = client.post("/ingest/image", files={"file": ("image_math.png", (FIX / "image_math.png").read_bytes(), "image/png")}).json()
    mq = answered(client, "12", "7", "5")
    assert mq and mq["answer"]["suggested_answer"] == "89", mq
    record("test_02_image_question", ocr_text=r["ocr_text"], question=summary(q), math_ocr=m["ocr_text"], math=summary(mq))


def test_03_video_frames(client, events):
    job = client.post("/ingest/video", files={"file": ("video_quiz.mp4", (FIX / "video_quiz.mp4").read_bytes(), "video/mp4")},
                      data={"sample_fps": "5"}).json()["job_id"]
    res = wait_for(lambda: (j := client.get(f"/jobs/{job}").json())["status"] in ("done", "failed") and j, 600, 1)
    assert res["status"] == "done", res
    q1 = answered(client, "planet", "moons", timeout=60)
    q2 = answered(client, "capital of australia", timeout=60)
    assert q1 and q2
    assert q1["options"] == ["Jupiter", "Saturn", "Uranus", "Neptune"], q1["options"]
    assert q2["options"] == ["Sydney", "Melbourne", "Canberra", "Perth"], q2["options"]
    assert q1["answer"]["option_index"] == 1 and q2["answer"]["option_index"] == 2
    st = res["stats"]
    total_frames = 13 * 25
    assert st["ocr_calls"] < st["frames_seen"] / 2, st      # not every frame is OCR'd
    assert len([q for q in questions(client) if q["status"] == "answered"]) == 2
    record("test_03_video_frames", job_stats=st, video_frames_total=total_frames, questions=[summary(q1), summary(q2)],
           ai_requests=client.get("/stats").json()["ai_requests"])


# ----------------------------------------------------------------------------- audio (tests 5-7)
AUDIO_CASES = {
    "en": (["planet", "moons"], "Which planet has the largest number of moons?"),
    "fr": (["capitale", "australie"], "Quelle est la capitale de l'Australie ?"),
    "ar": (["عاصمة", "اليابان"], "ما هي عاصمة اليابان؟"),
}


def _audio_case(client, events, lang, variant):
    keys, ref = AUDIO_CASES[lang]
    stream_wav(FIX / f"audio_{lang}{variant}.wav")
    q = wait_for(lambda: next((x for x in questions(client) if "audio" in x["source"] and x["status"] == "answered"), None), 60)
    assert q, f"no audio question; transcripts={transcripts(events)}"
    assert q["language"] == lang
    norm = normalize_for_match(q["question_text"])
    sim = fuzz.partial_ratio(normalize_for_match(ref), norm)
    tr = transcripts(events)
    assert all(t["language"] == lang for t in tr), tr
    assert events.of("audio.speech_start"), "speech start not signalled"
    assert any(e["data"]["active"] for e in events.of("capture.status")), "capture indicator not raised"
    return q, sim, tr


@pytest.mark.parametrize("variant", ["", "_noisy"])
def test_05_spoken_english(client, events, variant):
    q, sim, tr = _audio_case(client, events, "en", variant)
    assert sim >= 90, q["question_text"]
    record(f"test_05_spoken_english[{variant or 'clean'}]", question=summary(q), similarity=sim, transcripts=tr)


@pytest.mark.parametrize("variant", ["", "_noisy"])
def test_06_spoken_french(client, events, variant):
    q, sim, tr = _audio_case(client, events, "fr", variant)
    assert sim >= 90, q["question_text"]
    assert not any("geographie" in normalize_for_match(q["question_text"]) for _ in [0]), "intro phrase not dropped"
    record(f"test_06_spoken_french[{variant or 'clean'}]", question=summary(q), similarity=sim, transcripts=tr)


@pytest.mark.parametrize("variant", ["", "_noisy"])
def test_07_spoken_arabic(client, events, variant):
    q, sim, tr = _audio_case(client, events, "ar", variant)
    assert sim >= 85, q["question_text"]
    record(f"test_07_spoken_arabic[{variant or 'clean'}]", question=summary(q), similarity=sim, transcripts=tr)


def test_05b_speech_completeness(client, events):
    """Supporting checks for audio requirements 8/9: paused question joined, statements ignored,
    multi-sentence question keeps its numbers."""
    stream_wav(FIX / "audio_en_statement.wav")
    time.sleep(2)
    assert not [q for q in questions(client) if "audio" in q["source"]], "a statement became a question"
    stream_wav(FIX / "audio_en_paused.wav")
    q = answered(client, "longest", "africa", timeout=60)
    assert q, [x["question_text"] for x in questions(client)]
    assert not find(client, "in africa") or find(client, "in africa")["question_id"] == q["question_id"]
    stream_wav(FIX / "audio_en_multisentence.wav")
    wp = answered(client, "train", "far", timeout=60)
    assert wp and "120" in wp["question_text"] and "3" in wp["question_text"] and "5" in wp["question_text"]
    record("test_05b_speech_completeness", paused=summary(q), multi_sentence=summary(wp),
           audio_questions=len([x for x in questions(client) if "audio" in x["source"]]))


# ----------------------------------------------------------------------------- fusion (tests 8, 9)
def test_08_simultaneous_audio_and_visual(client, events):
    t = threading.Thread(target=stream_wav, args=(FIX / "audio_en.wav",), kwargs={"speed": 1.0})
    t.start()
    wait_for(lambda: events.of("audio.speech_start"), 10, 0.05)
    client.post("/ingest/image", files={"file": ("image_question.png", (FIX / "image_question.png").read_bytes(), "image/png")})
    t.join()
    q = wait_for(lambda: (x := find(client, "planet", "moons")) and x["status"] == "answered"
                 and x["source"] == ["visual", "audio"] and x, 60)
    assert q, questions(client)
    assert len(questions(client)) == 1
    st = client.get("/stats").json()
    assert st["ai_requests"] == 1, st
    assert q["options"] == ["Jupiter", "Saturn", "Uranus", "Neptune"]
    record("test_08_simultaneous_audio_and_visual", question=summary(q), variants=q["variants"], ai_requests=st["ai_requests"])


def test_09_no_duplicate_submission(client, events):
    png = (FIX / "image_question.png").read_bytes()
    jpg = (FIX / "image_question.jpg").read_bytes()
    client.post("/ingest/image", files={"file": ("a.png", png, "image/png")})
    client.post("/ingest/image", files={"file": ("b.jpg", jpg, "image/jpeg")})
    client.post("/ingest/browser", json={"page_id": "dup", "blocks": [
        {"text": "Which planet has the largest number of moons?"}, {"text": "A) Jupiter"}, {"text": "B) Saturn"},
        {"text": "C) Uranus"}, {"text": "D) Neptune"}]})
    q = answered(client, "planet", "moons")
    assert q
    # the same question again after it was answered
    client.post("/ingest/image", files={"file": ("c.png", png, "image/png")})
    client.post("/ingest/chat", json={"conversation_id": "x", "message_id": "1", "role": "assistant",
                                      "text": "Which planet has the largest number of moons? A) Jupiter B) Saturn C) Uranus D) Neptune"})
    time.sleep(3)
    st = client.get("/stats").json()
    qs = questions(client)
    assert len(qs) == 1, [x["question_text"] for x in qs]
    assert st["ai_requests"] == 1, st
    assert len(events.of("question.answered")) == 1
    record("test_09_no_duplicate_submission", detections_submitted=5, questions=len(qs), ai_requests=st["ai_requests"],
           suppressed_duplicates=st["suppressed_duplicates"], channels=qs[0]["channels"])
