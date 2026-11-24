"""Core data structures shared by every modality."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Modality(str, Enum):
    VISUAL = "visual"   # images, screenshots, video frames, browser OCR
    AUDIO = "audio"     # microphone / audio files
    BROWSER = "browser"  # DOM text from the authorized browser extension
    CHAT = "chat"       # chatbot conversation messages

    @property
    def family(self) -> str:
        """The spec reports sources as "visual" / "audio". Browser DOM and chatbot text are
        things the user *sees*, so they collapse into the visual family for display."""
        return "audio" if self is Modality.AUDIO else "visual"


class Status(str, Enum):
    INCOMPLETE = "incomplete"              # partial text still arriving
    SETTLING = "settling"                  # complete, waiting briefly for other modalities/options
    READY = "ready_for_analysis"
    ANALYZING = "analyzing"
    ANSWERED = "answered"
    FAILED = "failed"


@dataclass
class Observation:
    """One raw detection of a question candidate from a single modality."""
    text: str
    modality: Modality
    confidence: float
    language: str | None = None
    options: list[str] = field(default_factory=list)
    complete: bool = True
    origin: str = ""                 # e.g. "screenshot", "video:frame=120", "chat:conv1/msg4"
    stream_key: str | None = None    # identifies a progressive stream (same video region, same chat msg)
    context: list[str] = field(default_factory=list)  # prior conversation turns for follow-ups
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: float = 0.0         # monotonic seconds


@dataclass
class Discrepancy:
    field: str
    values: dict[str, str]           # modality -> value
    resolution: str
    resolved_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "values": self.values,
                "resolution": self.resolution, "resolved_value": self.resolved_value}


@dataclass
class Answer:
    suggested_answer: str | None
    option_index: int | None
    confidence: float
    explanation: str
    provider: str
    model: str | None
    duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class DetectedQuestion:
    question_text: str
    language: str
    options: list[str]
    confidence: float
    status: Status
    question_id: str = field(default_factory=lambda: "q_" + uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=utc_now_iso)
    modalities: set[Modality] = field(default_factory=set)
    observations: list[Observation] = field(default_factory=list)
    variants: dict[str, str] = field(default_factory=dict)        # modality -> text as that modality saw it
    discrepancies: list[Discrepancy] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    answer: Answer | None = None
    revision: int = 0
    analysis_requests: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    detected_to_answer_ms: int | None = None
    error: str | None = None

    @property
    def source(self) -> list[str]:
        fams = {m.family for m in self.modalities}
        return [f for f in ("visual", "audio") if f in fams]

    def to_dict(self) -> dict[str, Any]:
        """Spec-mandated shape plus extra fields the Android app renders."""
        return {
            "question_id": self.question_id,
            "question_text": self.question_text,
            "source": self.source,
            "language": self.language,
            "options": self.options,
            "timestamp": self.timestamp,
            "confidence": round(self.confidence, 3),
            "status": self.status.value,
            # extended fields
            "channels": sorted(m.value for m in self.modalities),
            "variants": self.variants,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "context": self.context,
            "revision": self.revision,
            "answer": self.answer.to_dict() if self.answer else None,
            "processing_ms": self.detected_to_answer_ms,
            "error": self.error,
            "origins": sorted({o.origin for o in self.observations if o.origin})[:10],
        }
