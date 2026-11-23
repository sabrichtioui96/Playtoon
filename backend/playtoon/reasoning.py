"""Answer generation. Claude (Anthropic API) when credentials are configured; otherwise an
offline answerer (arithmetic solver + small demo fact table) so the pipeline stays testable."""
from __future__ import annotations

import ast
import json
import logging
import operator
import re
import time
from dataclasses import dataclass

from .models import Answer, DetectedQuestion
from .text_utils import normalize_for_match

log = logging.getLogger(__name__)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "suggested_answer": {"type": "string"},
        "option_index": {"type": "integer", "description": "0-based index into options, or -1"},
        "confidence": {"type": "number"},
        "explanation": {"type": "string"},
        "used_variant": {"type": "string", "description": "which source reading was used when sources disagreed, else 'n/a'"},
    },
    "required": ["suggested_answer", "option_index", "confidence", "explanation", "used_variant"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You answer questions that Playtoon detected on the user's screen, in a chatbot conversation, or in speech.
Input text came from OCR and speech recognition, so it may contain recognition errors; infer the intended question.
Rules:
- If answer options are given, choose one and return its 0-based index in option_index; otherwise option_index = -1.
- If the sources disagree (see "discrepancies"), decide which reading is most plausible, answer that, and name it in used_variant.
- Use "conversation context" to resolve follow-up questions (pronouns, "what about X?").
- explanation: at most two short sentences, written in the same language as the question (English, French or Arabic).
- confidence: your probability (0-1) that suggested_answer is correct. Be calibrated.
- If the text is not actually answerable, say so in explanation, with suggested_answer "" and confidence 0."""


@dataclass
class ReasoningConfig:
    provider: str = "auto"          # auto | anthropic | offline
    model: str = "claude-opus-5-5"
    effort: str = "low"             # quiz answers are latency-sensitive; raise for harder material
    translate_to: str | None = None  # None = keep original language (default per spec)


def build_user_prompt(q: DetectedQuestion) -> str:
    payload = {
        "question": q.question_text,
        "language": q.language,
        "options": q.options,
        "sources": q.source,
        "variants": q.variants if len(set(q.variants.values())) > 1 else {},
        "discrepancies": [d.to_dict() for d in q.discrepancies],
        "conversation context": q.context[-6:],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


class ClaudeAnswerer:
    name = "anthropic"

    def __init__(self, cfg: ReasoningConfig):
        import anthropic
        self.cfg = cfg
        self.client = anthropic.AsyncAnthropic()

    async def answer(self, q: DetectedQuestion) -> Answer:
        import anthropic
        t0 = time.perf_counter()
        try:
            resp = await self.client.beta.messages.create(
                model=self.cfg.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_prompt(q) + (
                    f"\nTranslate the question to '{self.cfg.translate_to}' first and write the explanation in that language."
                    if self.cfg.translate_to else "")}],
                output_config={"effort": self.cfg.effort,
                               "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise RuntimeError(f"rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise RuntimeError(f"connection error: {e}") from e
        ms = int((time.perf_counter() - t0) * 1000)
        if resp.stop_reason == "refusal":
            return Answer(None, None, 0.0, "The model declined to answer this question.", self.name, resp.model, ms)
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(text)
        idx = data.get("option_index", -1)
        idx = idx if isinstance(idx, int) and 0 <= idx < len(q.options) else None
        ans = data.get("suggested_answer") or (q.options[idx] if idx is not None else None)
        return Answer(ans or None, idx, float(max(0.0, min(1.0, data.get("confidence", 0.0)))),
                      data.get("explanation", ""), self.name, resp.model, ms)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}


def _safe_eval(expr: str) -> float:
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 20:
                raise ValueError("exponent too large")
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "sqrt" and len(n.args) == 1:
            return ev(n.args[0]) ** 0.5
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr, mode="eval"))


def solve_arithmetic(text: str) -> str | None:
    t = text.translate(str.maketrans({"×": "*", "x": "*", "X": "*", "÷": "/", "−": "-", "^": "**", "²": "**2", "√": "sqrt"}))
    t = re.sub(r"\b(times|fois|multiplied by)\b", "*", t, flags=re.I)
    t = re.sub(r"\b(plus)\b", "+", t, flags=re.I)
    t = re.sub(r"\b(minus|moins)\b", "-", t, flags=re.I)
    t = re.sub(r"\b(divided by|divisé par)\b", "/", t, flags=re.I)
    m = re.findall(r"[\d.()]+(?:\s*(?:\*\*|[-+*/%])\s*[\d.()]+|\s*\*\*2)+|sqrt\s*\(?\s*\d+\s*\)?", t)
    if not m:
        return None
    expr = max(m, key=len).replace("sqrt", "sqrt(").replace("((", "(")
    if expr.count("(") > expr.count(")"):
        expr += ")" * (expr.count("(") - expr.count(")"))
    try:
        v = _safe_eval(expr)
    except Exception:
        return None
    return str(int(v)) if float(v).is_integer() else f"{v:.4g}"


# Tiny offline knowledge base used only when no AI provider is configured (demo / tests).
DEMO_FACTS = [
    (["planet", "most moons"], "Saturn", "Saturn has the most confirmed moons (over 270 as of 2025)."),
    (["planet", "largest number of moons"], "Saturn", "Saturn has the most confirmed moons (over 270 as of 2025)."),
    (["planete", "plus de lunes"], "Saturne", "Saturne possède le plus grand nombre de lunes confirmées."),
    (["capitale", "australie"], "Canberra", "Canberra est la capitale de l'Australie."),
    (["capital", "australia"], "Canberra", "Canberra is the capital of Australia."),
    (["capital", "japan"], "Tokyo", "Tokyo is the capital of Japan."),
    (["عاصمه", "اليابان"], "طوكيو", "طوكيو هي عاصمة اليابان."),
    (["longest river", "africa"], "Nile", "The Nile is the longest river in Africa."),
    (["largest ocean"], "Pacific Ocean", "The Pacific is the largest ocean on Earth."),
    (["wrote", "hamlet"], "William Shakespeare", "Hamlet was written by William Shakespeare."),
    (["capital", "france"], "Paris", "Paris is the capital of France."),
]


class OfflineAnswerer:
    name = "offline"

    async def answer(self, q: DetectedQuestion) -> Answer:
        t0 = time.perf_counter()
        nq = normalize_for_match(q.question_text + " " + " ".join(q.context))
        ans, expl, conf = None, "No AI provider configured (set ANTHROPIC_API_KEY or run `ant auth login`). Offline mode only solves arithmetic and a few demo facts.", 0.0
        arith = solve_arithmetic(q.question_text)
        if arith is not None:
            ans, expl, conf = arith, "Computed arithmetically.", 0.99
        else:
            for keys, a, e in DEMO_FACTS:
                if all(normalize_for_match(k) in nq for k in keys):
                    ans, expl, conf = a, e + " (offline demo knowledge)", 0.6
                    break
        idx = None
        if ans is not None and q.options:
            na = normalize_for_match(ans)
            for i, o in enumerate(q.options):
                if normalize_for_match(o) == na or na in normalize_for_match(o):
                    idx = i
                    break
        return Answer(ans, idx, conf, expl, self.name, None, int((time.perf_counter() - t0) * 1000))


def has_anthropic_credentials() -> bool:
    import os
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    import shutil
    import subprocess
    ant = shutil.which("ant")
    if not ant:
        return False
    try:
        out = subprocess.run([ant, "auth", "status"], capture_output=True, text=True, timeout=10).stdout
        return "(active)" in out
    except Exception:
        return False


def make_answerer(cfg: ReasoningConfig):
    if cfg.provider == "offline":
        return OfflineAnswerer()
    if cfg.provider == "anthropic" or (cfg.provider == "auto" and has_anthropic_credentials()):
        try:
            return ClaudeAnswerer(cfg)
        except Exception as e:     # missing SDK / creds
            log.warning("Claude unavailable (%s); using offline answerer", e)
    return OfflineAnswerer()
