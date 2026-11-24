"""Fast unit tests for parsing, chat context and fusion rules (no models loaded)."""
from playtoon.chat import ChatTracker
from playtoon.fusion import FusionConfig, QuestionManager
from playtoon.models import Modality, Observation, Status
from playtoon.text_utils import detect_language, extract_questions


def obs(text, mod, conf=0.95, t=0.0, complete=True, options=None, **meta):
    return Observation(text=text, modality=mod, confidence=conf, language=detect_language(text), complete=complete,
                       options=options or [], observed_at=100 + t, stream_key=f"{mod.value}:s", metadata=meta)


def test_parse_mcq_and_heading():
    qs = extract_questions("Space Trivia - Round 2\nWhich planet has the largest number of moons?\nA) Jupiter\nB)Saturn\nC) Uranus\nD) Neptune")
    assert len(qs) == 1 and qs[0].options == ["Jupiter", "Saturn", "Uranus", "Neptune"] and qs[0].complete


def test_languages():
    assert detect_language("Quelle est la capitale de l'Australie ?") == "fr"
    assert detect_language("ما هي عاصمة اليابان؟") == "ar"
    assert detect_language("Which river is the longest?") == "en"


def test_incomplete_and_statements():
    assert extract_questions("Which planet has the")[0].complete is False
    assert extract_questions("Great, let us continue.") == []
    assert extract_questions("Question 3: Solve for x:\n2x + 3 = 11")[0].text.endswith("2x + 3 = 11")


def test_progressive_text_single_question():
    m = QuestionManager(FusionConfig(settle_s=0.5))
    m.ingest(obs("Which planet has the", Modality.VISUAL, t=0, complete=False))
    m.ingest(obs("Which planet has the largest number of moons?", Modality.VISUAL, t=1))
    m.ingest(obs("Which planet has the largest number of moons?", Modality.VISUAL, t=2, options=["Jupiter", "Saturn"]))
    assert len(m.questions) == 1
    assert m.due(now=102.2) == [] and len(m.due(now=103.0)) == 1


def test_new_question_when_numbers_change_on_screen():
    m = QuestionManager()
    m.ingest(obs("What is 12 x 7?", Modality.VISUAL, t=0))
    m.ingest(obs("What is 13 x 7?", Modality.VISUAL, t=5))
    assert len(m.questions) == 2


def test_fusion_discrepancy_preserved():
    m = QuestionManager()
    m.ingest(obs("What is 12 x 7?", Modality.VISUAL, conf=0.8, t=0))
    ev = m.ingest(obs("What is 12 times 8?", Modality.AUDIO, conf=0.7, t=2, core_question="What is 12 times 8?"))
    assert len(m.questions) == 1
    q = next(iter(m.questions.values()))
    assert q.source == ["visual", "audio"]
    d = [x for x in q.discrepancies if x.field == "numbers"]
    assert d and d[0].values == {"visual": "12, 7", "audio": "12, 8"}
    assert set(q.variants) == {"visual", "audio"}


def test_answered_question_not_resubmitted():
    m = QuestionManager(FusionConfig(settle_s=0.1))
    m.ingest(obs("Who wrote Hamlet?", Modality.VISUAL, t=0))
    (q,) = m.due(now=101)
    m.mark_analyzing(q)
    q.status = Status.ANSWERED
    m.ingest(obs("Who wrote Hamlet?", Modality.AUDIO, t=3))
    m.ingest(obs("Who wrote Hamlet?", Modality.CHAT, t=4))
    assert m.due(now=110) == [] and m.ai_requests == 1 and q.source == ["visual", "audio"]


def test_chat_follow_up_and_roles():
    c = ChatTracker()
    assert c.ingest("c", "1", "assistant", "Hi! Let us warm up.", True) == []
    assert c.ingest("c", "2", "user", "What is your name?", True) == []          # user turns are context only
    o1 = c.ingest("c", "3", "assistant", "What is the capital of Japan?", True)
    o2 = c.ingest("c", "4", "assistant", "And what about Australia?", True)
    assert len(o1) == 1 and o1[0].metadata["follow_up"] is False
    assert o2[0].metadata["follow_up"] is True and any("Japan" in x for x in o2[0].context)


def test_numbered_questions_are_not_options():
    """Q&A pages number their questions ("1. What is QA?"); those must not be eaten as choices "1."."""
    qs = extract_questions("40 QA Interview Questions\n1. What is Quality Assurance?\nQA ensures quality.\n"
                           "2. What is the difference between QA and QC?\nQA is process oriented.\n3. What is a test plan?")
    assert [q.text for q in qs] == ["What is Quality Assurance?", "What is the difference between QA and QC?",
                                    "What is a test plan?"]
    mcq = extract_questions("Which of these is a prime number?\n1. 21\n2. 27\n3. 29\n4. 33")
    assert mcq[0].options == ["21", "27", "29", "33"]


def test_groq_rate_limit_falls_back_to_next_model(monkeypatch):
    """A 429 on one model puts it on cooldown and the same question is answered by the next model."""
    import asyncio
    import json as _json

    import httpx

    from playtoon.models import DetectedQuestion
    from playtoon.reasoning import OpenAICompatAnswerer, ReasoningConfig
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    def handler(request):
        model = _json.loads(request.content)["model"]
        calls.append(model)
        if model == "openai/gpt-oss-120b":
            return httpx.Response(429, text='{"error":{"message":"Rate limit reached ... Please try again in 7.5s."}}')
        return httpx.Response(200, json={"choices": [{"message": {"content": _json.dumps(
            {"suggested_answer": "4", "option_index": 1, "confidence": 0.9, "explanation": "2+2", "used_variant": "n/a"})}}]})

    a = OpenAICompatAnswerer("groq", ReasoningConfig(provider="groq"))
    a.client = httpx.AsyncClient(base_url="https://x", transport=httpx.MockTransport(handler))
    q = DetectedQuestion(question_text="What is 2+2?", language="en", options=["3", "4"], confidence=0.9, status=Status.READY)
    ans = asyncio.run(a.answer(q))
    assert ans.suggested_answer == "4" and ans.model == "openai/gpt-oss-20b"
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert 6 < a.cooldown["openai/gpt-oss-120b"] - __import__("time").monotonic() <= 7.5
    asyncio.run(a.answer(q))                       # 120b still cooling down: goes straight to 20b
    assert calls[-1] == "openai/gpt-oss-20b" and calls.count("openai/gpt-oss-120b") == 1
