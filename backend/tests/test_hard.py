"""Harder-question scorecard (English + French). Detection is always scored; answer correctness is
scored only when the server's answerer is Claude (offline mode cannot answer these)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from rapidfuzz import fuzz

from conftest import FIX, ROOT, record, wait_for
from hard_cases import AUDIO_CASES, CHAT_CASES, IMAGE_CASES
from playtoon.text_utils import extract_numbers, normalize_for_match as N
from test_acceptance import stream_wav

HARD = FIX / "hard"


def qs(c):
    return c.get("/questions").json()


def answer_ok(q: dict, expected: str) -> bool | None:
    a = q.get("answer") or {}
    if a.get("provider") != "anthropic":
        return None
    got = a.get("suggested_answer") or ""
    if a.get("option_index") is not None and q["options"]:
        got = q["options"][a["option_index"]] + " " + got
    ng, ne = N(got), N(expected)
    nums_e = extract_numbers(expected)
    if nums_e and set(nums_e) <= set(extract_numbers(got)):
        return True
    return ne in ng or fuzz.partial_ratio(ne, ng) >= 90


def opts_equal(a: list[str], b: list[str]) -> bool:
    return [N(x) for x in a] == [N(x) for x in b]


def latency(q: dict) -> int | None:
    return q.get("processing_ms")


@pytest.mark.parametrize("case", IMAGE_CASES, ids=[c["id"] for c in IMAGE_CASES])
def test_hard_image(client, case):
    t0 = time.time()
    r = client.post("/ingest/image", files={"file": (case["id"] + ".png", (HARD / f"{case['id']}.png").read_bytes(), "image/png")}).json()
    q = wait_for(lambda: next((x for x in qs(client) if x["status"] == "answered"), None), 90)
    wall = round(time.time() - t0, 2)
    assert q, f"no question detected; OCR: {r['ocr_text']!r}"
    sim = fuzz.ratio(N(case["question"]), N(q["question_text"]))
    ok_ans = answer_ok(q, case["answer"])
    record(f"test_hard_image[{case['id']}]", ocr=r["ocr_text"], detected=q["question_text"], similarity=sim,
           options=q["options"], language=q["language"], answer=(q["answer"] or {}).get("suggested_answer"),
           answer_correct=ok_ans, wall_s=wall)
    assert sim >= 90, (q["question_text"], case["question"])
    assert opts_equal(q["options"], case["options"]), (q["options"], case["options"])
    assert q["language"] == case["lang"]
    assert len([x for x in qs(client) if x["status"] != "incomplete"]) == 1
    if ok_ans is not None:
        assert ok_ans, (q["answer"], case["answer"])


@pytest.mark.parametrize("case", CHAT_CASES, ids=[c["id"] for c in CHAT_CASES])
def test_hard_chat(client, case):
    for i, (role, text) in enumerate(case["messages"]):
        client.post("/ingest/chat", json={"conversation_id": case["id"], "message_id": str(i), "role": role, "text": text})
        time.sleep(0.3)
    time.sleep(1.0)
    expected = case["expect"]
    got = wait_for(lambda: (l := [x for x in qs(client) if x["status"] == "answered"]) and len(l) >= len(expected) and l, 90) or []
    got = sorted(got, key=lambda x: x["timestamp"])
    detected = [x["question_text"] for x in qs(client)]
    results = []
    for exp in expected:
        q = max(got, key=lambda x: fuzz.ratio(N(exp["question"]), N(x["question_text"])), default=None)
        assert q is not None, detected
        sim = fuzz.ratio(N(exp["question"]), N(q["question_text"]))
        ok_ans = answer_ok(q, exp["answer"])
        results.append(dict(expected=exp["question"], detected=q["question_text"], similarity=sim,
                            context=q["context"], options=q["options"], answer=(q["answer"] or {}).get("suggested_answer"),
                            answer_correct=ok_ans))
        assert sim >= 90, (q["question_text"], exp["question"])
        if "options" in exp:
            assert opts_equal(q["options"], exp["options"]), (q["options"], exp["options"])
        if exp.get("follow_up"):
            assert q["context"], f"follow-up without context: {q}"
        if ok_ans is not None:
            assert ok_ans, (q["answer"], exp["answer"])
    record(f"test_hard_chat[{case['id']}]", results=results, all_detected=detected)
    assert len([x for x in qs(client) if x["status"] != "incomplete"]) == len(expected), detected


@pytest.mark.parametrize("variant", ["clean", "noisy"])
@pytest.mark.parametrize("case", AUDIO_CASES, ids=[c["id"] for c in AUDIO_CASES])
def test_hard_audio(client, events, case, variant):
    name = case["id"] + ("_noisy" if variant == "noisy" else "")
    stream_wav(HARD / f"{name}.wav", speed=3.0)
    q = wait_for(lambda: next((x for x in qs(client) if "audio" in x["source"] and x["status"] == "answered"), None), 90)
    tr = [e["data"]["text"] for e in events.of("transcript.final")]
    assert q, f"no question; transcripts={tr}"
    nq = N(q["question_text"])
    missing = [k for k in case["keywords"] if N(k) not in nq and not (extract_numbers(k) and set(extract_numbers(k)) <= set(extract_numbers(q["question_text"])))]
    sim = fuzz.token_set_ratio(N(case["question"]), nq)
    ok_ans = answer_ok(q, case["answer"])
    record(f"test_hard_audio[{case['id']}-{variant}]", transcripts=tr, detected=q["question_text"], similarity=sim,
           options=q["options"], language=q["language"], answer=(q["answer"] or {}).get("suggested_answer"),
           answer_correct=ok_ans)
    assert q["language"] == case["lang"]
    assert not missing, (missing, q["question_text"])
    assert sim >= 80, (q["question_text"], case["question"])
    if "options" in case:
        assert opts_equal(q["options"], case["options"]), (q["options"], case["options"])
    if ok_ans is not None:
        assert ok_ans, (q["answer"], case["answer"])


def test_hard_audio_with_host_vocabulary(client, events):
    """The host can enter topic terms (Settings -> Topic vocabulary); they bias Whisper's spelling.
    Default settings hear "len" as "LUN" on the clean clip; with the vocabulary it is exact."""
    try:
        client.put("/config", json={"asr_vocabulary": "Python, len(), strings"})
        stream_wav(HARD / "aud_en_technical.wav", speed=3.0)
        q = wait_for(lambda: next((x for x in qs(client) if "audio" in x["source"] and x["status"] == "answered"), None), 90)
        assert q, [e["data"]["text"] for e in events.of("transcript.final")]
        record("test_hard_audio_with_host_vocabulary", detected=q["question_text"])
        assert " len " in f" {q['question_text']} "
    finally:
        client.put("/config", json={"asr_vocabulary": ""})
