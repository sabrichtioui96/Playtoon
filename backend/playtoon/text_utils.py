"""Language-aware text utilities: language ID, question detection, option parsing,
completeness checks and normalisation for duplicate matching. Supports en / fr / ar."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")

_EN_WORDS = set("""the a an of and is are was were what which who whom whose when where why how
do does did can could would should will in on at to for with from by this that these those it its
has have had largest most many much number name planet river capital country year""".split())
_FR_WORDS = set("""le la les un une des du de et est sont était quel quelle quels quelles qui que
quoi quand où pourquoi comment combien dans sur pour avec par ce cette ces il elle ils elles a ont
au aux plus grand grande nombre pays capitale fleuve année est-ce""".split())

QUESTION_STARTERS = {
    "en": ["what", "which", "who", "whom", "whose", "when", "where", "why", "how", "is", "are", "was",
           "were", "do", "does", "did", "can", "could", "would", "should", "will", "has", "have",
           "name", "choose", "select", "identify", "calculate", "solve", "find", "compute",
           "evaluate", "determine", "true or false", "fill in", "complete", "explain", "describe",
           "give", "list", "estimate", "simplify", "convert"],
    "fr": ["quel", "quelle", "quels", "quelles", "qui", "que", "qu'", "quoi", "quand", "où", "ou se",
           "pourquoi", "comment", "combien", "est-ce", "lequel", "laquelle", "lesquels", "lesquelles",
           "choisissez", "choisis", "sélectionnez", "calculez", "calcule", "trouvez", "trouve",
           "résolvez", "nommez", "citez", "donnez", "vrai ou faux", "complétez", "expliquez"],
    "ar": ["ما", "ماذا", "من", "متى", "أين", "اين", "لماذا", "كيف", "كم", "هل", "أي", "اي", "أيّ",
           "اختر", "احسب", "أوجد", "اوجد", "حدد", "اذكر", "صح أم خطأ", "ما هو", "ما هي", "بماذا", "لمن"],
}
# Words that, when they end an utterance, mean the speaker has not finished.
TRAILING_INCOMPLETE = {
    "en": {"the", "a", "an", "of", "and", "or", "to", "in", "on", "at", "for", "with", "by", "is", "are",
           "was", "which", "that", "from", "between", "than", "as", "its", "their", "his", "her", "but",
           "into", "about", "if", "whether", "has", "have", "does", "do", "what", "how", "many", "much"},
    "fr": {"le", "la", "les", "un", "une", "des", "du", "de", "d'", "et", "ou", "à", "au", "aux", "en",
           "dans", "sur", "pour", "avec", "par", "est", "sont", "qui", "que", "quel", "quelle", "entre",
           "mais", "si", "son", "sa", "ses", "plus", "combien"},
    "ar": {"في", "من", "إلى", "الى", "على", "عن", "و", "أو", "او", "ثم", "التي", "الذي", "هل", "ما", "كم",
           "بين", "مع"},
}

# A, A), A., (A), a-, 1), 1., •, -, Arabic letter options أ) ب) ج) د)
OPTION_LINE_RE = re.compile(
    r"^\s*(?:\(?([A-Ha-h]|[1-8]|[أبجدهـو])[\)\].:\-–]|[•●○◯□☐▢◻\-–*])\s*(.+?)\s*$")
INLINE_OPTIONS_RE = re.compile(r"(?:^|\s)\(?([A-Ha-h])[\).:]\s+(.+?)(?=\s+\(?[A-Ha-h][\).:]\s+|$)")

MATH_TRANSLATE = str.maketrans({"×": "x", "✕": "x", "÷": "/", "−": "-", "–": "-", "—": "-",
                                "²": "^2", "³": "^3", "√": "sqrt", "·": "*", "＝": "=", "？": "?",
                                "؟": "?", "‏": "", "‎": ""})


def detect_language(text: str) -> str:
    """Script + stop-word heuristic. Robust on very short strings where n-gram models fail."""
    if not text.strip():
        return "und"
    ar = len(ARABIC_RE.findall(text))
    lat = len(LATIN_RE.findall(text))
    if ar > lat:
        return "ar"
    words = re.findall(r"[a-zà-ÿ'-]+", text.lower())
    en = sum(w in _EN_WORDS for w in words)
    fr = sum(w in _FR_WORDS for w in words) + 2 * len(re.findall(r"[éèêàùçôîœ]", text.lower()))
    if en == fr == 0:
        return "en" if lat else "und"
    return "fr" if fr > en else "en"


def normalize_for_match(text: str) -> str:
    """Lower-case, strip accents/punctuation/diacritics, unify math symbols."""
    t = text.translate(MATH_TRANSLATE).lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[ًٌٍَُِّْـ]", "", t)                 # Arabic harakat + tatweel
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    t = re.sub(r"\b(times|multiplied by|fois|multiplie par)\b", " x ", t)
    t = re.sub(r"\b(divided by|divise par)\b", " / ", t)
    t = re.sub(r"\b(equals|egale?|is equal to)\b", " = ", t)
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", " x ", t)
    t = re.sub(r"[^\w\s+\-*/=^.]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_EN_NUMS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
            "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
            "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
            "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}
_FR_NUMS = {"zéro": 0, "un": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
            "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14,
            "quinze": 15, "seize": 16, "vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50,
            "soixante": 60, "cent": 100}


def extract_numbers(text: str) -> list[str]:
    nums = [n.replace(",", ".") for n in NUMBER_RE.findall(text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))]
    for w in re.findall(r"[a-zà-ÿ]+", text.lower()):
        if w in _EN_NUMS:
            nums.append(str(_EN_NUMS[w]))
        elif w in _FR_NUMS and w not in {"un", "six"}:
            nums.append(str(_FR_NUMS[w]))
    return nums


def proper_nouns(text: str) -> set[str]:
    """Capitalised tokens that are not sentence-initial: cheap named-entity proxy."""
    out = set()
    for sent in re.split(r"(?<=[.?!])\s+", text):
        toks = re.findall(r"[A-ZÀ-Ý][\wÀ-ÿ'-]+", sent)
        first = sent.strip().split(" ")[0] if sent.strip() else ""
        out.update(t for t in toks if t != first)
    return out


def starts_like_question(sentence: str, lang: str) -> bool:
    s = sentence.strip().lower().lstrip("«\"'“(¿")
    s = re.sub(r"^(question|q)\s*\d*\s*[:.)-]\s*", "", s)
    s = re.sub(r"^\d+\s*[.)-]\s*", "", s)
    for l in ([lang] if lang in QUESTION_STARTERS else []) + [k for k in QUESTION_STARTERS if k != lang]:
        for st in QUESTION_STARTERS[l]:
            if s == st or s.startswith(st + " ") or (st.endswith("'") and s.startswith(st)):
                return True
            if l == "ar" and s.startswith(st):     # Arabic proclitics (وما، فهل)
                return True
            if l == "ar" and s[:1] in "وف" and s[1:].startswith(st):
                return True
    return False


def is_question_sentence(sentence: str, lang: str) -> bool:
    s = sentence.strip()
    if len(s) < 4:
        return False
    if s.endswith(("?", "؟", "？")):
        return True
    if re.search(r"(=\s*\?|=\s*_+|\?\s*$|_{3,})", s):     # "12 x 7 = ?" / fill-in-the-blank
        return True
    return starts_like_question(s, lang) and len(s.split()) >= 3


def looks_incomplete(text: str, lang: str, require_terminal: bool = True) -> bool:
    """True when the text is plausibly cut off mid-question (progressive rendering or a pause in speech).
    With require_terminal, an interrogative sentence without ? . ! is treated as still in progress;
    the fusion layer promotes such text once it has stayed unchanged long enough."""
    s = text.strip()
    if require_terminal and s and not s.endswith(("?", "؟", "？", ".", "!", "۔")) and starts_like_question(s, lang) \
            and not re.search(r"=\s*\?|_{3,}", s):
        return True
    if not s:
        return True
    if s.endswith(("?", "؟", "？")):
        return False
    if s.endswith(("...", "…", ",", ":", ";", "-")):
        return True
    words = re.findall(r"[\w'’-]+", s.lower())
    if not words:
        return True
    if words[-1] in TRAILING_INCOMPLETE.get(lang, set()):
        return True
    # Question-word start but no terminal punctuation and very short -> likely still being spoken/typed
    if starts_like_question(s, lang) and len(words) < 4 and not s.endswith((".", "!")):
        return True
    return False


@dataclass
class ParsedQuestion:
    text: str
    options: list[str] = field(default_factory=list)
    complete: bool = True
    language: str = "en"
    preamble: str = ""       # non-question context that precedes the question


GLUED_RE = re.compile(r"\b(What|Which|Who|Where|When|How|Why|Quel|Quelle)(is|are|was|were|does|do|did|has|have|many|much|est|sont)\b")


def _clean_line(line: str) -> str:
    line = GLUED_RE.sub(r"\1 \2", line)          # OCR drops spaces: "Whatis" -> "What is"
    return re.sub(r"\s+", " ", line.replace("\u200f", "").replace("\u200e", "")).strip()


def parse_options(lines: list[str]) -> tuple[list[str], list[int]]:
    """Return option texts and the indices of lines consumed."""
    opts, used = [], []
    for i, line in enumerate(lines):
        m = OPTION_LINE_RE.match(line)
        if m and m.group(2) and len(m.group(2)) <= 120:
            opts.append(m.group(2).strip())
            used.append(i)
        elif opts and i == used[-1] + 1 and not is_question_sentence(line, detect_language(line)) and len(line) <= 60 and not line.endswith("."):
            # OCR sometimes splits marker and text onto separate lines ("A)" then "Jupiter")
            if lines[used[-1]].strip().rstrip(").:").strip() in "ABCDEFGHabcdefgh" and len(lines[used[-1]].strip()) <= 3:
                opts[-1] = line
                used.append(i)
    if len(opts) < 2:
        return [], []
    return opts, used


def _starts_new_question(block: str, nxt: str, lang: str) -> bool:
    """Is `nxt` a new question rather than the wrapped continuation of `block`?
    "Space Trivia - Round 2" / "Which planet ..." -> new.  "... which country" / "was he born?" -> wrapped."""
    if not nxt or not starts_like_question(nxt, lang):
        return False
    last = re.findall(r"[\w'’-]+", block.lower())
    if last and last[-1] in TRAILING_INCOMPLETE.get(lang, set()) | TRAILING_INCOMPLETE["en"]:
        return False
    first = nxt.lstrip("«\"'“(¿")[:1]
    return not first.islower()          # Arabic has no case: isLower() is False -> treated as new


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[?؟？.!])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def extract_questions(raw_text: str, lang_hint: str | None = None) -> list[ParsedQuestion]:
    """Find question(s) in a block of text (OCR output, DOM text, chat message, transcript).

    Multi-line layout is respected: answer-option lines following a question attach to it.
    Several consecutive questions in one block yield several ParsedQuestions.
    """
    text = raw_text.translate(str.maketrans({"‏": "", "‎": ""}))
    raw_lines = [_clean_line(l) for l in text.splitlines() if _clean_line(l)]
    if not raw_lines:
        return []
    lang = lang_hint or detect_language(text)
    # Re-join wrapped inline options: "... C) Tokyo D)" + "Nagoya"
    lines: list[str] = []
    for l in raw_lines:
        if lines and re.search(r"(^|\s)\(?[A-Ha-h][\).]$", lines[-1]):
            lines[-1] += " " + l
        else:
            lines.append(l)

    # Expand inline options "A) x B) y C) z" on a single line
    expanded: list[str] = []
    for line in lines:
        inline = INLINE_OPTIONS_RE.findall(line)
        if len(inline) >= 2:
            head = INLINE_OPTIONS_RE.split(line)[0].strip()
            first = re.search(r"(?:^|\s)\(?[A-Ha-h][\).:]\s+", line)
            if first:
                head = line[: first.start()].strip()
            if head:
                expanded.append(head)
            expanded.extend(f"{k}) {v}" for k, v in inline)
        else:
            expanded.append(line)
    lines = expanded

    results: list[ParsedQuestion] = []
    i = 0
    pending_preamble: list[str] = []
    while i < len(lines):
        line = lines[i]
        if OPTION_LINE_RE.match(line) and not results:
            i += 1
            continue
        # Join wrapped lines that belong to one sentence (OCR / layout wraps)
        block = line
        j = i + 1
        while j < len(lines) and not OPTION_LINE_RE.match(lines[j]) and not re.search(r"[?؟？.!:]$", block) \
                and not _starts_new_question(block, lines[j], lang):
            block += " " + lines[j]
            j += 1
        sentences = split_sentences(block)
        q_sents = [s for s in sentences if is_question_sentence(s, lang)]
        if q_sents:
            # keep the statement sentences immediately before the question as context
            # e.g. "Here is a geography question. Which river is the longest?"
            q_text_parts, pre = [], []
            for s in sentences:
                if is_question_sentence(s, lang):
                    q_text_parts.append(s)
                elif not q_text_parts:
                    pre.append(s)
                else:
                    q_text_parts.append(s)
            # Several distinct questions in one block -> split
            groups: list[str] = []
            for s in q_text_parts:
                if groups and is_question_sentence(groups[-1], lang) and groups[-1].endswith(("?", "؟")) \
                        and is_question_sentence(s, lang) and s.endswith(("?", "؟")):
                    groups.append(s)
                elif groups:
                    groups[-1] += " " + s
                else:
                    groups.append(s)
            # "Solve for x:" followed by the expression on the next line(s)
            while groups[-1].endswith(":") and j < len(lines) and not OPTION_LINE_RE.match(lines[j]):
                groups[-1] += " " + lines[j]
                j += 1
            # Options following
            k = j
            opt_lines = []
            while k < len(lines) and (OPTION_LINE_RE.match(lines[k]) or (opt_lines and len(lines[k]) <= 60
                                                                         and not is_question_sentence(lines[k], lang))):
                opt_lines.append(lines[k])
                k += 1
            options, used = parse_options(opt_lines)
            if options:
                k = j + used[-1] + 1
            else:
                k = j
            preamble = " ".join(pending_preamble + pre).strip()
            for gi, g in enumerate(groups):
                is_last = gi == len(groups) - 1
                complete = not looks_incomplete(g, lang)
                results.append(ParsedQuestion(text=g, options=options if is_last else [],
                                              complete=complete or bool(options and is_last),
                                              language=detect_language(g) if not lang_hint else lang,
                                              preamble=preamble))
            pending_preamble = []
            i = k
        else:
            # A trailing fragment that starts like a question ("Which planet has the") -> incomplete question
            if j >= len(lines) and starts_like_question(block, lang) and not block.endswith("."):
                results.append(ParsedQuestion(text=block, complete=False, language=lang,
                                              preamble=" ".join(pending_preamble)))
            else:
                pending_preamble = (pending_preamble + [block])[-2:]
            i = j
    return results
