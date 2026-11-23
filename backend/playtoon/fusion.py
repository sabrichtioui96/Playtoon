"""Multimodal fusion: the central question manager.

Every modality produces Observations. The manager decides whether an observation is
  * a progressive update of a question already being tracked (same stream, text grew),
  * the same question seen through another modality (merge, record discrepancies), or
  * a new question,
and decides *when* a question is ready to be analysed (complete + short settle window so the
other modality and late-rendering answer options can join), guaranteeing one AI request per
question unless its content materially changes."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import DetectedQuestion, Discrepancy, Modality, Observation, Status, utc_now_iso
from .text_utils import extract_numbers, looks_incomplete, normalize_for_match, proper_nouns

log = logging.getLogger(__name__)


@dataclass
class FusionConfig:
    settle_s: float = 1.2            # wait for other modality / options after a question completes
    multimodal_settle_s: float = 0.3  # already seen by both families: submit almost immediately
    cross_modal_window_s: float = 25.0
    same_stream_window_s: float = 600.0
    dedup_ttl_s: float = 600.0
    match_threshold: float = 82.0
    max_revisions: int = 2
    incomplete_ttl_s: float = 30.0
    stable_promote_s: float = 2.5


def _core(o: Observation) -> str:
    return o.metadata.get("core_question") or o.text


class QuestionManager:
    def __init__(self, cfg: FusionConfig | None = None):
        self.cfg = cfg or FusionConfig()
        self.questions: dict[str, DetectedQuestion] = {}
        self._deadline: dict[str, float] = {}
        self._streams: dict[str, str] = {}          # stream_key -> question_id of its latest question
        self.ai_requests = 0
        self.suppressed_duplicates = 0

    # ------------------------------------------------------------------ matching
    def _similarity(self, q: DetectedQuestion, o: Observation) -> float:
        a = normalize_for_match(_core(o))
        best = 0.0
        texts = {q.question_text, *q.variants.values(), *(ob.metadata.get("core_question", ob.text) for ob in q.observations[-6:])}
        for t in texts:
            b = normalize_for_match(t)
            if not a or not b:
                continue
            s = max(fuzz.ratio(a, b), fuzz.token_set_ratio(a, b) * 0.97)
            # progressive text: one is a prefix of the other
            short, long_ = sorted((a, b), key=len)
            if len(short) >= 12 and long_.startswith(short[: max(12, len(short) - 3)]):
                s = max(s, 92.0)
            best = max(best, s)
        return best

    def _find_match(self, o: Observation, now: float) -> tuple[DetectedQuestion | None, float]:
        best, best_s = None, 0.0
        for q in self.questions.values():
            age = now - q.last_seen
            same_family = o.modality.family in {m.family for m in q.modalities}
            window = self.cfg.dedup_ttl_s if q.status == Status.ANSWERED else (
                self.cfg.same_stream_window_s if same_family else self.cfg.cross_modal_window_s)
            if age > window:
                continue
            s = self._similarity(q, o)
            if s < self.cfg.match_threshold:
                continue
            nums_o, nums_q = set(extract_numbers(_core(o))), set(extract_numbers(q.question_text))
            if nums_o != nums_q and nums_o and nums_q:
                # Same modality family seeing different numbers = the screen moved on to a new question
                # ("12 x 7" then "13 x 7"). Different family within a short window = a discrepancy.
                if same_family or age > self.cfg.cross_modal_window_s:
                    continue
            if o.options and q.options and same_family:
                ov = len({normalize_for_match(x) for x in o.options} & {normalize_for_match(x) for x in q.options})
                if ov == 0 and q.status == Status.ANSWERED:
                    continue                      # identical stem, entirely new choices -> new question
            if s > best_s:
                best, best_s = q, s
        return best, best_s

    # ------------------------------------------------------------------ ingest
    def ingest(self, o: Observation) -> list[tuple[str, DetectedQuestion]]:
        now = o.observed_at or time.monotonic()
        o.observed_at = now
        q, score = self._find_match(o, now)
        if q is None:
            if not o.complete and len(normalize_for_match(o.text)) < 8:
                return []
            q = DetectedQuestion(question_text=o.text, language=o.language or "und", options=list(o.options),
                                 confidence=o.confidence * (1.0 if o.complete else 0.6),
                                 status=Status.SETTLING if o.complete else Status.INCOMPLETE,
                                 first_seen=now, last_seen=now)
            q.modalities.add(o.modality)
            q.observations.append(o)
            q.variants[o.modality.value] = o.text
            q.context = list(o.context)
            self.questions[q.question_id] = q
            if o.stream_key:
                self._streams[o.stream_key] = q.question_id
            if o.complete:
                self._schedule(q, now)
            return [("question.detected", q)]
        return self._merge(q, o, now)

    def _merge(self, q: DetectedQuestion, o: Observation, now: float) -> list[tuple[str, DetectedQuestion]]:
        was_answered = q.status in (Status.ANSWERED, Status.ANALYZING, Status.READY)
        new_family = o.modality.family not in {m.family for m in q.modalities}
        old_options = list(q.options)
        old_text = q.question_text
        old_discrepancies = len(q.discrepancies)
        q.modalities.add(o.modality)
        q.observations.append(o)
        q.observations = q.observations[-40:]
        q.last_seen = now
        if o.stream_key:
            self._streams[o.stream_key] = q.question_id
        prev_variant = q.variants.get(o.modality.value)
        if o.complete or prev_variant is None:
            # within one modality the newest (progressively longer) text wins
            if prev_variant is None or o.complete or len(o.text) >= len(prev_variant):
                q.variants[o.modality.value] = o.text

        complete_obs = [x for x in q.observations if x.complete]
        if not complete_obs:
            q.question_text = max(q.variants.values(), key=len)
            return [("question.updated", q)] if q.question_text != old_text else []

        # ---- text resolution across modalities
        by_family: dict[str, Observation] = {}
        for x in complete_obs:
            cur = by_family.get(x.modality.family)
            if cur is None or x.observed_at >= cur.observed_at:
                by_family[x.modality.family] = x
        vis, aud = by_family.get("visual"), by_family.get("audio")
        if vis and aud:
            canonical = vis if vis.confidence >= 0.75 or vis.confidence >= aud.confidence else aud
            q.question_text = _core(canonical)
            self._record_discrepancies(q, vis, aud)
            pre = aud.text[: max(0, len(aud.text) - len(_core(aud)))].strip()
            if pre and pre not in q.context:
                q.context.append(f"spoken context: {pre}")
        else:
            latest = vis or aud
            q.question_text = latest.text
        q.language = max(complete_obs, key=lambda x: x.confidence).language or q.language

        # ---- options: visual rendering is authoritative for exact wording; keep both if they differ
        if o.options:
            if not q.options:
                q.options = list(o.options)
            elif [normalize_for_match(x) for x in o.options] != [normalize_for_match(x) for x in q.options]:
                if o.modality.family == "visual":
                    if any(x.modality.family == "audio" and x.options for x in q.observations):
                        self._add_disc(q, "options", {"audio": " | ".join(q.options), "visual": " | ".join(o.options)},
                                       "visual options preferred (exact on-screen wording)", " | ".join(o.options))
                    q.options = list(o.options)     # dynamically changing / progressively rendered choices
                else:
                    self._add_disc(q, "options", {"visual": " | ".join(q.options), "audio": " | ".join(o.options)},
                                   "kept on-screen options; spoken options sent to the model as a variant", " | ".join(q.options))
        for x in o.context:
            if x not in q.context:
                q.context.append(x)
        q.context = q.context[-8:]

        fams = {m.family for m in q.modalities}
        confs = {}
        for x in complete_obs:
            confs[x.modality.family] = max(confs.get(x.modality.family, 0.0), x.confidence)
        p_wrong = 1.0
        for c in confs.values():
            p_wrong *= (1 - min(c, 0.99))
        q.confidence = min(0.995, 1 - p_wrong) * (0.9 if q.discrepancies else 1.0)

        events: list[tuple[str, DetectedQuestion]] = []
        if q.status == Status.INCOMPLETE:
            self._schedule(q, now)
            events.append(("question.updated", q))
        elif q.status == Status.SETTLING:
            if len(fams) > 1:
                self._schedule(q, now)           # shorten settle: both families present
            elif q.options != old_options or q.question_text != old_text:
                self._schedule(q, now)           # content still changing: restart settle timer
            events.append(("question.updated", q))
        elif was_answered:
            material = (q.options != old_options and bool(old_options) or
                        (q.options and not old_options) or len(q.discrepancies) > old_discrepancies)
            if material and q.revision < self.cfg.max_revisions:
                q.revision += 1
                q.status = Status.SETTLING
                self._schedule(q, now)
                events.append(("question.revised", q))
            else:
                self.suppressed_duplicates += 1
                events.append(("question.updated" if new_family or q.question_text != old_text else "question.duplicate", q))
        return events

    def _add_disc(self, q: DetectedQuestion, field: str, values: dict, resolution: str, resolved: str | None) -> None:
        for d in q.discrepancies:
            if d.field == field and d.values == values:
                return
        q.discrepancies.append(Discrepancy(field, values, resolution, resolved))

    def _record_discrepancies(self, q: DetectedQuestion, vis: Observation, aud: Observation) -> None:
        vt, at = _core(vis), _core(aud)
        nv, na = extract_numbers(vt), extract_numbers(at)
        if sorted(nv) != sorted(na) and (nv or na):
            self._add_disc(q, "numbers", {"visual": ", ".join(nv) or "-", "audio": ", ".join(na) or "-"},
                           "unresolved: both readings sent to the model, which must state which it used"
                           if vis.confidence < 0.9 else "on-screen value preferred (OCR confidence >= 0.9); spoken value kept as variant",
                           ", ".join(nv) if vis.confidence >= 0.9 else None)
        pv = {p.lower() for p in proper_nouns(vt)}
        pa = {p.lower() for p in proper_nouns(at)}
        diff = {p for p in pv ^ pa if not any(fuzz.ratio(p, o) > 85 for o in (pa if p in pv else pv))}
        if diff and pv and pa:
            self._add_disc(q, "names", {"visual": ", ".join(sorted(pv)), "audio": ", ".join(sorted(pa))},
                           "on-screen spelling preferred for names", ", ".join(sorted(pv)))
        sim = fuzz.ratio(normalize_for_match(vt), normalize_for_match(at))
        if sim < 88 and not any(d.field in ("numbers", "names") for d in q.discrepancies):
            self._add_disc(q, "wording", {"visual": vt, "audio": at},
                           "same question, different wording: both variants sent to the model", None)

    def _schedule(self, q: DetectedQuestion, now: float) -> None:
        fams = {m.family for m in q.modalities}
        q.status = Status.SETTLING
        self._deadline[q.question_id] = now + (self.cfg.multimodal_settle_s if len(fams) > 1 else self.cfg.settle_s)

    # ------------------------------------------------------------------ scheduling
    def due(self, now: float | None = None, hold=None) -> list[DetectedQuestion]:
        """Questions whose settle window elapsed -> READY. Highest priority first:
        multimodal > has options > confidence. `hold(q)` may delay a question (e.g. speech is
        being transcribed right now and may be the same question)."""
        now = time.monotonic() if now is None else now
        ready = []
        for qid, dl in list(self._deadline.items()):
            q = self.questions.get(qid)
            if q is None or q.status != Status.SETTLING:
                self._deadline.pop(qid, None)
                continue
            if now >= dl and not (hold and hold(q, now)):
                self._deadline.pop(qid)
                q.status = Status.READY
                q.timestamp = utc_now_iso()
                ready.append(q)
        ready.sort(key=lambda q: (len(q.source), bool(q.options), q.confidence), reverse=True)
        return ready

    def mark_analyzing(self, q: DetectedQuestion) -> None:
        q.status = Status.ANALYZING
        q.analysis_requests += 1
        self.ai_requests += 1

    def expire(self, now: float | None = None) -> list[DetectedQuestion]:
        """Housekeeping: (1) on-screen text without terminal punctuation that has stayed unchanged
        for `stable_promote_s` is promoted to complete (e.g. "Name the largest ocean" in a slide);
        speech is never promoted, since an unfinished sentence there is genuinely incomplete.
        (2) incomplete questions older than the TTL are reported once as expired."""
        now = time.monotonic() if now is None else now
        out = []
        for q in list(self.questions.values()):
            if q.status == Status.INCOMPLETE and all(m.family == "visual" for m in q.modalities):
                last = q.observations[-1]
                if now - last.observed_at >= self.cfg.stable_promote_s and \
                        not looks_incomplete(last.text, q.language, require_terminal=False) and len(last.text.split()) >= 4:
                    last.complete = True
                    last.metadata["promoted"] = "stable on screen"
                    q.question_text = last.text
                    self._schedule(q, now)
                    out.append(q)
                    continue
            if q.status == Status.INCOMPLETE and now - q.last_seen > self.cfg.incomplete_ttl_s and not q.observations[-1].metadata.get("expired"):
                q.observations[-1].metadata["expired"] = True
                out.append(q)
        return out

    def history(self, limit: int = 200) -> list[DetectedQuestion]:
        return sorted(self.questions.values(), key=lambda q: q.first_seen, reverse=True)[:limit]
