"""Evidence-gap narration in the writer's text: "Who signs the remaining decisions is not in the
evidence.", "the documents don't say which deadlines fall after it", "each deadline is its effective
decide-by" (an echo of a writer rule). Code drops such a sentence after the first and such a clause anywhere,
so recorded answers read the same without a new prompt. The first sentence keeps its gap when the gap is the
answer ("The evidence has no clocks from the previous advisory, so I can't say ...")."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

SUBJECT = r"(?:the\s+)?(?:evidence|documents?|platform(?:\s+data)?|data|records?|sources?|board)"
NEGATION = (
    r"(?:does\s+not|doesn't|do\s+not|don't|has\s+no|have\s+no|gives?\s+no|shows?\s+no|says?\s+nothing|"
    r"names?\s+no|lists?\s+no)"
)
GAP_RE = re.compile(
    rf"\b{SUBJECT}\s+{NEGATION}\b|\b(?:is|are)\s+not\s+in\s+(?:the|my)\s+evidence\b|\bnot\s+in\s+my\s+evidence\b|"
    r"\bshows?\s+no\s+verdict\b|\b(?:is|are)\s+not\s+(?:shown|given|listed|stated)\s*[.]|\b(?:dowody|dokumenty|dane)\s+nie\s+(?:m[oó]wi[aą]|podaj[aą]|pokazuj[aą]|"
    r"wskazuj[aą]|zawieraj[aą])\b|\bnie\s+ma\s+(?:tego\s+)?w\s+(?:dowodach|dokumentach)\b",
    re.IGNORECASE,
)
CLAUSE_RE = re.compile(
    rf",?\s+(?:but|and|though|although)\s+{SUBJECT}\s+{NEGATION}\b[^.;]*|"
    r",\s+and\s+(?:each\s+deadline\s+is\s+its|their\s+deadlines\s+are)\s+effective\s+decide-by(?:\s+times?)?",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"((?<=[.!?])\s+(?=[A-Z\"(]))")


NAMED_IN_BRACKETS = re.compile(r"\((?:its\s+)?(?:onsite\s+)?generators?\s+(GEN-[A-Z0-9]+(?:-[A-Z0-9]+)*)\)")


def tidy(text: str) -> str:
    """ "PS-38 (generator GEN-PS38-COPPERLEAF)": the chip already says "onsite generator" (V4-02)."""
    return NAMED_IN_BRACKETS.sub(r"(\1)", text)


def trim(text: str, first: bool = True) -> str:
    """The text without gap sentences after the first and without gap clauses. `first` is False for a block
    that does not start the answer, so its first sentence may go too."""
    pieces = SENTENCE.split(text)
    sentences, seps = pieces[0::2], ["", *pieces[1::2]]
    out: list[tuple[str, str]] = []
    for n, (sep, part) in enumerate(zip(seps, sentences, strict=True)):
        if not GAP_RE.search(part) and not CLAUSE_RE.search(part):
            out.append((sep, part))
            continue
        cut = CLAUSE_RE.sub("", part).rstrip()
        if cut != part.rstrip() and not GAP_RE.search(cut):
            out.append(
                (sep, (cut if cut.endswith((".", "!", "?")) else cut + ".") + part[len(part.rstrip()) :])
            )
        elif (first and n == 0) or len(sentences) == 1:
            out.append((sep, part))
    if not out or len(out) == len(sentences) and all(o[1] == s for o, s in zip(out, sentences, strict=True)):
        return text
    lead = text[: len(text) - len(text.lstrip())]
    return lead + out[0][1].lstrip() + "".join(sep + part for sep, part in out[1:])


def trim_content(content: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The model's content blocks with gaps trimmed in the text blocks that carry no citations (not for the
    frozen R29 eval replays, `personas.EXTRA` off)."""
    from sgw.agent.tools.personas import EXTRA

    if not EXTRA["on"]:
        return [dict(b) for b in content]
    out: list[dict[str, Any]] = []
    started = False
    for block in content:
        b = dict(block)
        if b.get("type") == "text" and not b.get("citations") and isinstance(b.get("text"), str):
            b["text"] = trim(tidy(b["text"]), first=not started)
        if b.get("type") == "text" and str(b.get("text") or "").strip():
            started = True
        out.append(b)
    return out
