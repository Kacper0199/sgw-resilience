"""K15 verifier with the D-073 id rule.

Model-written text passes only when:
- every slot names an evidence ref of the run and a field that ref offers;
- no brace is left over after the valid slots are removed (half slots, `{E12}`, nested braces);
- every digit-bearing token outside slots exactly equals an id from the run's evidence bundle, the asset and
  document registry, or the closed vocabulary of step codes; shape alone never passes
  (no id-shaped regex: an invented `PS-91` or `FDR-AIK-9999` is rejected);
- no number word (zero to ninety, hundred, thousand, dozen, quarter, third, half, double, triple, twice,
  couple, percent) and no character with a Unicode numeric value outside ASCII (`七`, `½`, `Ⅻ`);
- no sentence claims authority (approval, authorisation, clearance, "go ahead", "proceed with");
- no link or markup (`://`, `](`, `<`, `>`): text is rendered as plain text.
Text is NFKC-normalised first, so full-width or other Unicode digits are judged like ASCII digits.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sgw.contracts.evidence import SLOT_RE
from sgw.contracts.vocab import DecisionStep

REPO_ROOT = Path(__file__).resolve().parents[4]
NETWORK_FILE = REPO_ROOT / "data" / "fixtures" / "helene" / "network.json"
ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
TOKEN_RE = re.compile(r"[^\s,;!?()\[\]\"'`]+")
EDGE_PUNCT = ".:,;!?)(\"'`*_"
LOOSE_SLOT_RE = re.compile(r"\{[^{}]*\}|[{}]")
NUMBER_WORD_RE = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundreds?|thousands?|millions?|billions?|dozens?|quarters?|thirds?|halfs?|halves|half|double|triple|"
    r"twice|couple|percent|per\s*cent)\b",
    re.IGNORECASE,
)
AUTHORITY_RE = re.compile(
    r"\b(?:(?:has|have|had|was|were|is|are)\s+(?:been\s+|now\s+)?(?:approved|authori[sz]ed|signed\s+off|cleared)"
    r"|I\s+(?:approve|authori[sz]e|order|dispatch|have\s+dispatched)"
    r"|(?:approval|authori[sz]ation)\s+(?:is\s+|was\s+)?(?:granted|given|confirmed)"
    r"|go\s+ahead|proceed\s+with|cleared\s+to)\b"
    r"|(?:^|(?<=[.!?:;]\s)|(?<=\n))\s*(?:approved|authori[sz]ed|cleared)\b",
    re.IGNORECASE,
)
MARKUP_RE = re.compile(r"://|\]\(|[<>]")


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


def vocabulary_tokens() -> frozenset[str]:
    """Closed codes a reader needs in prose. Tier and data-class codes are not among them: a tier is a
    policy result and reaches text only through a code-filled slot. "911" is part of a facility's name (the
    Ian exercise's 911 dispatch center), not a quantity."""
    codes = {s.value for s in DecisionStep} | {f"W{i}" for i in range(1, 14)}
    return frozenset(codes | {"N+1", "P10", "P50", "P90", "911"})


@lru_cache(maxsize=1)
def asset_registry(path: Path = NETWORK_FILE) -> frozenset[str]:
    """Ids of the named assets (pump stations, feeders, yards, crews, substation, hospital) in the Helene
    world: every string or key in the network file that has id shape. Exact membership is the test; the
    shape only selects what to load."""
    if not path.is_file():
        return frozenset()
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                if isinstance(k, str) and ID_RE.match(k):
                    found.add(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and ID_RE.match(node):
            found.add(node)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return frozenset(found)


def known_ids(bundle_ids: Iterable[str], extra: Iterable[str] = ()) -> frozenset[str]:
    return frozenset(bundle_ids) | asset_registry() | vocabulary_tokens() | frozenset(extra)


def _is_numeric(ch: str) -> bool:
    try:
        unicodedata.numeric(ch)
    except (TypeError, ValueError):
        return False
    return True


def _strip(token: str) -> str:
    out = token.strip(EDGE_PUNCT)
    if out.endswith("'s"):
        out = out[:-2]
    return out


def verify(text: str, fields: Mapping[str, set[str]], ids: frozenset[str]) -> list[Violation]:
    norm = unicodedata.normalize("NFKC", text)
    problems: list[Violation] = []
    for m in SLOT_RE.finditer(norm):
        ref, field = f"E{m['n']}", m["field"]
        if ref not in fields:
            problems.append(Violation("unknown_evidence", m.group(0)))
        elif field not in fields[ref]:
            problems.append(Violation("unknown_slot_field", m.group(0)))
    rest = SLOT_RE.sub(" ", norm)
    for m in LOOSE_SLOT_RE.finditer(rest):
        problems.append(Violation("malformed_slot", m.group(0)[:40]))
    rest = LOOSE_SLOT_RE.sub(" ", rest)
    for m in TOKEN_RE.finditer(rest):
        token = _strip(m.group(0))
        if not re.search(r"\d", token):
            continue
        candidates = {token, *token.split("/")}
        if token in ids or all(c in ids for c in token.split("/") if re.search(r"\d", c)):
            continue
        has_letters = bool(re.search(r"[A-Za-z]", token))
        code = "unknown_id" if has_letters and any(ID_RE.match(c) for c in candidates) else "stray_digit"
        problems.append(Violation(code, token[:40]))
    for m in NUMBER_WORD_RE.finditer(rest):
        problems.append(Violation("number_word", m.group(0)))
    raw = SLOT_RE.sub(" ", text)
    for ch in sorted({c for c in raw + rest if not c.isascii() and _is_numeric(c)}):
        problems.append(Violation("numeric_char", ch))
    for m in MARKUP_RE.finditer(rest):
        problems.append(Violation("markup", m.group(0)))
    for m in AUTHORITY_RE.finditer(rest):
        problems.append(Violation("authority_claim", m.group(0)))
    return problems
