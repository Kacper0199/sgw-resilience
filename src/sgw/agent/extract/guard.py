"""Instruction detector for untrusted free text (field notes, tickets, public alert text, user turns).

It reuses the RAG input guard's folding and patterns and adds what a note or ticket carries that a
document does not: role labels (`System:`, `assistant:`), claims of approval or signature ("counts as the
second signature", "supervisor approved"), and orders addressed to the system (approve, close a ticket,
dispatch, raise priority, reveal the prompt). Text is split into sentences (case-insensitive, so a lower-
case `assistant:` after a full stop is its own sentence); a flagged sentence is withheld from every prompt
and kept only in quarantine. Detection is deterministic: the model's own opinion never clears a flag."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass

from sgw.agent.rag.guard import flags as rag_flags
from sgw.agent.rag.guard import fold

WITHHELD = "[withheld: instruction-like text]"

_EXTRA: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("canary", re.compile(r"\bCANARY-[A-Z0-9][A-Z0-9-]{2,}", re.IGNORECASE)),
    (
        "role_label",
        re.compile(r"(?:^|[\s(\[\"'])(?:system|assistant|ai|developer|copilot|model)\s*:", re.IGNORECASE),
    ),
    (
        "authority_claim",
        re.compile(
            r"\bcounts?\s+as\s+(?:the\s+|a\s+|an\s+)?(?:second\s+|final\s+|official\s+)?"
            r"(?:signature|approval|sign-?off|authori[sz]ation|co-?sign)"
            r"|\b(?:second|final)\s+signature\b"
            r"|\b(?:supervisor|ic|incident\s+commander|manager|director|duty\s+manager)\s+"
            r"(?:has\s+)?(?:approved|authori[sz]ed|signed\s+off|said\s+to\s+(?:approve|send|dispatch))"
            r"|\b(?:is|was|has\s+been|are|were|have\s+been)\s+(?:pre-?)?(?:approved|authori[sz]ed)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "delayed_trigger",
        re.compile(
            r"\b(?:on|in|at|during)\s+(?:the\s+)?(?:next|following|later)\s+(?:turn|message|run|reply|answer|step)\b"
            r"|\bcall\s+(?:the\s+)?[a-z_]+\s+tool\b|\bcall\s+(?:dispatch|draft_proposal|approve)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_order",
        re.compile(
            r"\b(?:approve|authori[sz]e|sign\s+off)\s+(?:the\s+|this\s+|my\s+|all\s+)?"
            r"(?:fuel|crew|plan|request|order|proposal|ticket|dispatch|work\s+order)"
            r"|\bclose\s+(?:the\s+)?(?:ticket|work\s+order|wo)\b"
            r"|\b(?:send|dispatch|move)\s+all\s+crews\b"
            r"|\b(?:raise|move|set|bump)\s+(?:this|it|my|our)\b.{0,40}\b(?:top|first|highest)\s+priority\b"
            r"|\b(?:lower|raise|change)\s+every\s+risk\b"
            r"|\breply\s+with\s+your\b|\b(?:reveal|print|show|repeat)\s+(?:your|the)\s+(?:system\s+)?"
            r"(?:prompt|instructions)\b"
            r"|\brun\s+this\s+(?:sql|query|command)\b|\b(?:update|delete|insert|drop)\s+(?:from\s+|into\s+)?"
            r"[a-z_]+\s+(?:set|where|values|table)\b",
            re.IGNORECASE,
        ),
    ),
)
_SENTENCE = re.compile(r"(?<=[.!?;])\s+")


_B64 = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _decoded(text: str) -> list[str]:
    """Printable text hidden in base64 tokens, so an encoded instruction is judged like a plain one."""
    out: list[str] = []
    for token in _B64.findall(text):
        try:
            raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if decoded.isprintable() and sum(c.isalpha() for c in decoded) >= len(decoded) // 2:
            out.append(decoded)
    return out


def instruction_flags(text: str) -> list[str]:
    found: set[str] = set()
    for i, candidate in enumerate([text, *_decoded(text)]):
        folded = fold(candidate)
        hits = set(rag_flags(candidate)) | {name for name, pat in _EXTRA if pat.search(folded)}
        if hits and i:
            hits.add("encoded")
        found |= hits
    return sorted(found)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GuardedText:
    original: str
    shown: str
    withheld: tuple[Span, ...]

    @property
    def instructions_detected(self) -> bool:
        return bool(self.withheld)

    @property
    def reasons(self) -> list[str]:
        return sorted({r for s in self.withheld for r in s.reasons})

    def overlaps_withheld(self, start: int, end: int) -> bool:
        return any(start < s.end and s.start < end for s in self.withheld)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _SENTENCE.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def guard_untrusted(text: str) -> GuardedText:
    """Withhold every sentence that carries an instruction; the rest is shown to the model unchanged."""
    withheld: list[Span] = []
    parts: list[str] = []
    for start, end in sentence_spans(text):
        reasons = instruction_flags(text[start:end])
        if reasons:
            withheld.append(Span(start, end, tuple(reasons)))
            if not parts or parts[-1] != WITHHELD:
                parts.append(WITHHELD)
        else:
            parts.append(text[start:end])
    return GuardedText(text, " ".join(parts), tuple(withheld))


_TAG = re.compile(r"</?\s*[A-Za-z][\w:.-]*\s*/?>")


def neutralise_tags(text: str) -> str:
    """Tag-shaped text (`</report>`, `<question>`, `<system/>`) in untrusted input cannot close or open the
    prompt's own delimiters: its angle brackets become look-alikes (U+2039, U+203A)."""
    return _TAG.sub(lambda m: m.group(0).replace("<", "\u2039").replace(">", "\u203a"), text)
