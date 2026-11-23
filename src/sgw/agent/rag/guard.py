"""Input guard for retrieved text: content that addresses an automated reader, carries links or tries to
override instructions is withheld before any passage reaches a model (search_result content, chunk-header
prompts).

Retrieved documents are data. A field record can carry an injected instruction written in house style
(ICS 214 entry, ICS 213 message, vendor ticket, OCR'd note), so the guard works on the units a reader sees:
a paragraph or step is checked as one string (hard wraps joined), then only its flagged sentences are withheld
(the whole paragraph when the attack spans sentences); in a table, each
logical row (its continuation lines joined) is checked and withheld alone, so the rest of the record stays
usable. Text is folded first (NFKC, format and zero-width characters removed, accents stripped, Cyrillic and
Greek look-alikes mapped to Latin, digit look-alikes in words), so homoglyph spellings match. The index
keeps the original text, so the record is still found by search.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

WITHHELD = "[line withheld by the input guard: text addressed to an automated system]"

CONFUSABLES = str.maketrans(
    {
        "а": "a", "А": "A", "в": "B", "В": "B", "е": "e", "Е": "E", "ё": "e", "і": "i", "І": "I", "ї": "i",
        "ј": "j", "к": "k", "К": "K", "м": "M", "М": "M", "н": "H", "Н": "H", "о": "o", "О": "O", "р": "p",
        "Р": "P", "с": "c", "С": "C", "т": "T", "Т": "T", "у": "y", "У": "Y", "х": "x", "Х": "X", "ѕ": "s",
        "Ѕ": "S", "ԁ": "d", "ɡ": "g", "ӏ": "l", "Ӏ": "I",
        "α": "a", "Α": "A", "β": "B", "Β": "B", "ε": "e", "Ε": "E", "η": "n", "Η": "H", "ι": "i", "Ι": "I",
        "κ": "k", "Κ": "K", "μ": "M", "Μ": "M", "ν": "v", "Ν": "N", "ο": "o", "Ο": "O", "ρ": "p", "Ρ": "P",
        "τ": "T", "Τ": "T", "υ": "u", "Υ": "Y", "χ": "x", "Χ": "X", "ζ": "Z", "Ζ": "Z",
        "ı": "i", "ℓ": "l", "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
        "’": "'", "‘": "'", "“": '"', "”": '"',
    }
)  # fmt: skip
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[(\"'])")
_DIGIT_IN_WORD = re.compile(r"(?<=[a-z])[0-9@$]|[0-9@$](?=[a-z])", re.IGNORECASE)
_DIGIT_MAP = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}

_READER = (
    r"(?:assistant|copilot|chat\s?bot|bot|llm|ai|a\.i\.|artificial\s+intelligence|language\s+models?|"
    r"(?:ai|automated|automatic)\s+(?:agent|system|model|tool|assistant|reader|summari[sz]er|pipeline)s?|"
    r"automated\s+(?:readers?|summar(?:y|ies|i[sz]ation)|tools?|systems?)|summar(?:y|i[sz](?:ing|ation|er))\s+"
    r"(?:tools?|models?|systems?|bots?))"
)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "addresses_reader",
        re.compile(
            rf"(?:^|[\s(\[\"':;])(?:dear\s+|hey\s+|attention\s+|attn:?\s+)?{_READER}\s*(?:,|:|\s[-=]+\s)",
            re.IGNORECASE,
        ),
    ),
    ("role_label", re.compile(r"^\W*(?:ai|assistant|copilot|chat\s?bot)\s*:", re.IGNORECASE)),
    (
        "reader_directive",
        re.compile(
            rf"\b{_READER}\s+(?:should|must|shall|need\s+to|are\s+to|is\s+to|will|may\s+only)\s+(?:not\s+)?"
            r"(?:say|state|report|answer|reply|treat|classify|ignore|mark|record|tell|use|cite|close|approve|skip)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "note_for_reader",
        re.compile(
            rf"\b(?:note|message|instructions?|reminder|directive|request|warning)s?\s+(?:for|to)\s+"
            rf"(?:the\s+|any\s+|all\s+|an\s+|a\s+)?{_READER}",
            re.IGNORECASE,
        ),
    ),
    (
        "conditional_reader",
        re.compile(
            rf"\b(?:if|when|while)\s+(?:you\s+are|you're|this\s+is\s+read\s+by|read\s+by)\s+(?:an?\s+|the\s+)?"
            rf"{_READER}|\b{_READER}\s+(?:reading|processing|summari[sz]ing|parsing)\s+(?:this|these)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "override",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|overrule|supersede)\s+(?:all\s+|any\s+|the\s+|your\s+|its\s+)?"
            r"(?:previous|prior|above|earlier|other|existing|original|system)\s+(?:guidance|instructions?|rules?|"
            r"prompts?|procedures?|directions?|text)?"
            r"|\bsystem\s+prompt\b|\bdo\s+not\s+cite\b|\bin\s+every\s+answer\b|\bwhen\s+asked\s+(?:about|for)\b"
            r"|\byou\s+are\s+now\b|\bfrom\s+now\s+on\s+(?:you|answer|say|report)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "link",
        re.compile(
            r"https?://|www\.[a-z0-9-]+\.[a-z]{2,}|\b[a-z0-9-]+\.(?:example|xyz|top|click)/", re.IGNORECASE
        ),
    ),
    ("canary", re.compile(r"\bCANARY-[A-Z0-9]{4,}\b", re.IGNORECASE)),
)


@dataclass(frozen=True)
class GuardResult:
    text: str
    withheld: tuple[str, ...]

    @property
    def tainted(self) -> bool:
        return bool(self.withheld)


def fold(text: str) -> str:
    """Comparison form: compatibility forms, invisible characters, accents and look-alike letters removed."""
    norm = unicodedata.normalize("NFKC", text)
    norm = "".join(ch for ch in norm if unicodedata.category(ch) != "Cf")
    norm = norm.translate(CONFUSABLES)
    norm = "".join(ch for ch in unicodedata.normalize("NFKD", norm) if not unicodedata.combining(ch))
    norm = _DIGIT_IN_WORD.sub(lambda m: _DIGIT_MAP.get(m.group(0), m.group(0)), norm)
    return " ".join(norm.split())


def flags(text: str) -> list[str]:
    folded = fold(text)
    return [name for name, pat in _PATTERNS if pat.search(folded)]


def _first_cell(line: str) -> str:
    parts = line.split("|")
    return parts[1].strip() if len(parts) > 2 else ""


def _rows(lines: list[str]) -> list[tuple[int, int]]:
    """Logical rows of a rendered table as line ranges: a row starts where the first cell is not empty."""
    rows: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        if rows and rows[-1][1] == i and not _first_cell(line):
            rows[-1] = (rows[-1][0], i + 1)
        else:
            rows.append((i, i + 1))
    return rows


def _row_text(lines: list[str]) -> str:
    cells: list[list[str]] = []
    for line in lines:
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        for k, part in enumerate(parts):
            if k >= len(cells):
                cells.append([])
            if part:
                cells[k].append(part)
    return " | ".join(" ".join(c) for c in cells)


def guard_block(text: str) -> GuardResult:
    """Guard one content block. A paragraph or step is checked as one string (wraps joined); flagged
    sentences are withheld, or the whole paragraph when no single sentence carries the attack; in a table
    each logical row is checked as one string and only that row is withheld."""
    lines = text.split("\n")
    if not lines[0].lstrip().startswith(("|", "+")):
        joined = " ".join(line.strip() for line in lines)
        reasons = flags(joined)
        if not reasons:
            return GuardResult(text, ())
        sentences = _SENTENCE_SPLIT.split(joined)
        bad = [i for i, sent in enumerate(sentences) if flags(sent)]
        if not bad or len(sentences) == 1:
            return GuardResult(WITHHELD, (",".join(reasons),))
        kept = [WITHHELD if i in bad else sent for i, sent in enumerate(sentences)]
        merged = [x for k, x in enumerate(kept) if not (x == WITHHELD and k and kept[k - 1] == WITHHELD)]
        return GuardResult(" ".join(merged), (",".join(reasons),))
    drop: set[int] = set()
    found: list[str] = []
    for start, end in _rows(lines):
        reasons = flags(_row_text(lines[start:end]))
        if reasons:
            found.append(",".join(reasons))
            drop.update(range(start, end))
    if not drop:
        return GuardResult(text, ())
    out: list[str] = []
    for i, line in enumerate(lines):
        if i in drop:
            if i - 1 not in drop:
                out.append(f"| {WITHHELD}")
        else:
            out.append(line)
    return GuardResult("\n".join(out), tuple(found))


def guard_text(text: str) -> GuardResult:
    """Guard a multi-block text whose blocks are separated by blank lines."""
    parts = [guard_block(p) for p in text.split("\n\n")]
    return GuardResult("\n\n".join(p.text for p in parts), tuple(r for p in parts for r in p.withheld))
