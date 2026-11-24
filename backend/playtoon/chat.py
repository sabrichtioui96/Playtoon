"""Chatbot conversation tracking.

Messages arrive from the browser extension (or any integration) as they render; streaming
messages are re-sent with the same message_id as they grow. Only assistant/bot messages are
scanned for questions; user messages are kept as context. A short rolling context lets
follow-ups ("What about Saturn?", "Et pour le Canada ?", "وماذا عن فرنسا؟") be interpreted."""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field

from .models import Modality, Observation
from .text_utils import detect_language, extract_questions

FOLLOW_UP_RE = {
    "en": re.compile(r"^(and|what about|how about|and what about|what of|same (question )?for|and for|"
                     r"why|how come|really|which one|is it|are they|does it|did it|was it|what if)\b|"
                     r"\b(it|that|this|they|them|those|these|he|she|its|their|the same|instead|then)\b", re.I),
    "fr": re.compile(r"^(et|et pour|et si|et qu'en est-il|qu'en est-il|même question|pourquoi|"
                     r"lequel|laquelle)\b|\b(il|elle|ils|elles|ce|cela|ça|celui|celle|le même|la même)\b", re.I),
    "ar": re.compile(r"^(و?ماذا عن|وماذا|و?كذلك|ولماذا|وهل|وكم|وما|ولو)|(هو|هي|هم|ذلك|هذا|هذه|نفس)"),
}


@dataclass
class ChatMessage:
    message_id: str
    role: str          # "assistant" | "user" | "system"
    text: str
    final: bool
    updated: float


@dataclass
class Conversation:
    conversation_id: str
    messages: "dict[str, ChatMessage]" = field(default_factory=dict)
    order: deque = field(default_factory=lambda: deque(maxlen=12))
    last_questions: deque = field(default_factory=lambda: deque(maxlen=3))
    emitted: dict = field(default_factory=dict)   # message_id -> set of question texts already emitted

    def context_lines(self, exclude: str | None = None, n: int = 6) -> list[str]:
        lines = []
        for mid in list(self.order)[-n - 1:]:
            if mid == exclude:
                continue
            m = self.messages[mid]
            lines.append(f"{m.role}: {m.text[:300]}")
        return lines[-n:]


def is_follow_up(text: str, lang: str) -> bool:
    words = text.split()
    rx = FOLLOW_UP_RE.get(lang, FOLLOW_UP_RE["en"])
    # short questions referring back, or with pronouns that need an antecedent
    return bool(rx.search(text)) and len(words) <= 14 or len(words) <= 4


class ChatTracker:
    def __init__(self, stable_ms: int = 900):
        self.convs: dict[str, Conversation] = {}
        self.stable_ms = stable_ms

    def ingest(self, conversation_id: str, message_id: str, role: str, text: str, final: bool,
               now: float | None = None) -> list[Observation]:
        now = time.monotonic() if now is None else now
        conv = self.convs.setdefault(conversation_id, Conversation(conversation_id))
        prev = conv.messages.get(message_id)
        if prev is None:
            conv.order.append(message_id)
        conv.messages[message_id] = ChatMessage(message_id, role.lower(), text, final, now)
        if role.lower() not in ("assistant", "bot", "agent", "system"):
            return []      # the user's own messages are context, never "detected questions"
        lang = detect_language(text)
        out: list[Observation] = []
        already = conv.emitted.setdefault(message_id, set())
        for q in extract_questions(text, lang):
            # While a message is still streaming, only a question with terminal punctuation followed by
            # more text (or a final message) is trusted; the trailing sentence may still be growing.
            if not final and not q.complete:
                out.append(self._obs(conv, message_id, q, lang, now, complete=False))
                continue
            if q.text in already and not q.options:
                continue
            ctx: list[str] = []
            follow = is_follow_up(q.text, lang) and bool(conv.last_questions)
            if follow:
                ctx = conv.context_lines(exclude=message_id)
            obs = self._obs(conv, message_id, q, lang, now, complete=q.complete, ctx=ctx)
            obs.metadata["follow_up"] = follow
            if follow:
                obs.metadata["refers_to"] = conv.last_questions[-1]
            out.append(obs)
            if q.complete:
                already.add(q.text)
                if final or q.text.endswith(("?", "؟")):
                    if not conv.last_questions or conv.last_questions[-1] != q.text:
                        conv.last_questions.append(q.text)
        return out

    def _obs(self, conv: Conversation, mid: str, q, lang: str, now: float, complete: bool,
             ctx: list[str] | None = None) -> Observation:
        return Observation(text=q.text, modality=Modality.CHAT, confidence=0.97, language=lang,
                           options=q.options, complete=complete, origin=f"chat:{conv.conversation_id}/{mid}",
                           stream_key=f"chat:{conv.conversation_id}/{mid}", context=ctx or [],
                           observed_at=now, metadata={"preamble": q.preamble,
                                                      "final": bool(conv.messages[mid].final and complete)})
