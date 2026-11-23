"""The platform map and glossary the Ask navigator reads: pages, tabs, query parameters, what each page
shows, who can open it, and the web's own term definitions.

`platform_map.yaml` is derived from the web routes; the glossary is the Help page's (`web/src/content/
glossary*.ts`), copied to `data/reference/platform_glossary.json` by `python -m
sgw.agent.copilot.platform_map` so the API image needs no web sources (a test keeps the copy in step). Links
are built here by code and only to pages the role can open; the model never writes one."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import yaml

MAP_FILE = Path(__file__).with_name("platform_map.yaml")
REPO = Path(__file__).resolve().parents[4]
GLOSSARY_FILE = REPO / "data" / "reference" / "platform_glossary.json"
WEB_GLOSSARY = REPO / "web" / "src" / "content"
ENTRY_RE = re.compile(
    r'([a-zA-Z_0-9]+|"[^"]+"):\s*\{\s*term:\s*"((?:[^"\\]|\\.)*)",\s*text:\s*"((?:[^"\\]|\\.)*)"', re.S
)
WORD_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
        "show",
        "find",
        "see",
        "get",
        "tell",
        "about",
        "there",
    ]
)
MAX_LINKS = 4


def fold(text: str) -> str:
    """Lower case without diacritics (Polish letters included), so a question typed without them matches."""
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


PL_STEMS: tuple[tuple[str, str], ...] = (
    ("wod", "water"),
    ("zdjec", "photos"),
    ("fot", "photos"),
    ("obraz", "images"),
    ("powodz", "flood"),
    ("zalan", "flood"),
    ("map", "map"),
    ("decyz", "decisions"),
    ("termin", "deadline"),
    ("prognoz", "forecast"),
    ("huragan", "hurricane"),
    ("burz", "storm"),
    ("ekip", "crews"),
    ("brygad", "crews"),
    ("zespol", "crews"),
    ("gotow", "readiness"),
    ("odpraw", "briefing"),
    ("podsumow", "summary"),
    ("sytuac", "situation"),
    ("dzieje", "happening"),
    ("awari", "outage"),
    ("przerw", "outage"),
    ("prad", "outage"),
    ("cisnien", "pressure"),
    ("szpital", "hospital"),
    ("pomp", "pump"),
    ("zbiornik", "tank"),
    ("powiadom", "notifications"),
    ("pomoc", "help"),
    ("slowni", "glossary"),
    ("pojec", "term"),
    ("znaczy", "meaning"),
    ("raport", "report"),
    ("podpis", "signature"),
    ("zatwierdz", "approval"),
    ("ryzyk", "risk"),
    ("zdrow", "health"),
    ("uszkodz", "damage"),
    ("szkod", "damage"),
)


def words(text: str) -> set[str]:
    """Content words, folded; Polish stems also give the English word the page vocabulary uses (the
    keyword fallback; the router model gives English topics for any language)."""
    out: set[str] = set()
    for w in WORD_RE.findall(fold(text)):
        if w in STOP or len(w) < 2:
            continue
        out.add(w)
        out.update(en for stem, en in PL_STEMS if w.startswith(stem))
    return out


@dataclass(frozen=True)
class Page:
    key: str
    label: str
    path: str
    shows: str
    words: frozenset[str]
    params: Mapping[str, str] = field(default_factory=dict)
    tabs: Mapping[str, str] = field(default_factory=dict)
    roles: frozenset[str] = frozenset()
    actions: str = ""

    def open_to(self, function: str) -> bool:
        return not self.roles or function in self.roles

    def fact(self) -> str:
        tabs = f" Tabs: {', '.join(self.tabs.values())}." if self.tabs else ""
        acts = f" {self.actions}" if self.actions else ""
        return f"{self.label} page ({self.path}): {self.shows}{tabs}{acts}"


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def pages() -> dict[str, Page]:
    out: dict[str, Page] = {}
    for p in _raw()["pages"]:
        out[p["key"]] = Page(
            key=p["key"],
            label=p["label"],
            path=p["path"],
            shows=" ".join(str(p["shows"]).split()),
            words=frozenset(fold(w) for w in p.get("words") or []),
            params=dict(p.get("params") or {}),
            tabs={str(k): str(v) for k, v in (p.get("tabs") or {}).items()},
            roles=frozenset(p.get("roles") or []),
            actions=str(p.get("actions") or ""),
        )
    return out


def role_label(function: str) -> str:
    return str((_raw()["roles"].get(function) or {}).get("label") or function.replace("_", " "))


def role_focus(function: str) -> list[str]:
    return list((_raw()["roles"].get(function) or {}).get("focus") or ["decisions", "brief", "map"])


def web_glossary(directory: Path = WEB_GLOSSARY) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("glossary*.ts")):
        for key, term, text in ENTRY_RE.findall(path.read_text(encoding="utf-8")):
            out[key.strip('"')] = {"term": _unescape(term), "text": _unescape(text)}
    return out


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace("\\n", " ")


ACRONYMS: Mapping[str, str] = {
    "ETR": "Estimated time of restoration: when power is expected to be back for customers. The platform"
    " gives a median and a range; a global ETR covers the whole system, ETR by area each operating area.",
    "BWA": "Boil-water advisory (boil-water notice): customers in a water zone must boil tap water before"
    " drinking it until clean samples lift the notice.",
    "OMS": "Outage management system: SGW's own log of outage events on its feeders.",
    "AMI": "Smart meters (advanced metering infrastructure): meters that report whether a home has power.",
    "SCADA": "The control system that reads and runs pump stations, tanks and substations remotely.",
    "EOC": "Emergency operations centre: where the storm response is run.",
    "NHC": "National Hurricane Center: it issues the storm advisories and the forecast cone.",
}


@lru_cache(maxsize=1)
def glossary() -> dict[str, dict[str, str]]:
    """The Help page terms, plus the acronyms people ask about that Help only uses inside longer terms."""
    if GLOSSARY_FILE.is_file():
        data: dict[str, dict[str, str]] = json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    else:
        data = web_glossary()
    return {**data, **{f"acronym_{k.lower()}": {"term": k, "text": v} for k, v in ACRONYMS.items()}}


def href(page: Page, **params: str | None) -> str:
    query = {k: v for k, v in params.items() if v}
    return page.path + (f"?{urlencode(query)}" if query else "")


def link(kind: str, key: str, label: str | None = None, **params: str | None) -> dict[str, str]:
    page = pages()[key]
    return {"kind": kind, "label": label or f"{page.label} page", "href": href(page, **params), "page": key}


def page_scores(text: str, topics: Iterable[str] = ()) -> list[tuple[float, Page]]:
    asked = words(text) | {w for t in topics for w in words(t)}
    ranked: list[tuple[float, Page]] = []
    for page in pages().values():
        hits = sum(1.0 for w in asked if w in page.words or _stem_hit(w, page.words))
        if fold(page.label) in fold(text):
            hits += 2
        if hits:
            ranked.append((hits, page))
    ranked.sort(key=lambda kv: (-kv[0], list(pages()).index(kv[1].key)))
    return ranked


def _stem_hit(word: str, vocab: frozenset[str]) -> bool:
    return len(word) >= 5 and any(len(v) >= 5 and word[:5] == v[:5] for v in vocab)


def find_pages(text: str, topics: Iterable[str], function: str, limit: int = 3) -> list[Page]:
    return [p for _, p in page_scores(text, topics) if p.open_to(function)][:limit]


def find_terms(text: str, topics: Iterable[str], limit: int = 4) -> list[dict[str, str]]:
    asked = words(text) | {w for t in topics for w in words(t)}
    phrases = [fold(t) for t in topics if t.strip()]
    scored: list[tuple[float, str, dict[str, str]]] = []
    for key, entry in glossary().items():
        term = fold(entry["term"])
        tw = words(entry["term"])
        score = 3.0 if term in fold(text) or term in phrases else 0.0
        score += 2.0 * len(tw & asked) / max(len(tw), 1)
        score += 0.3 * len(words(entry["text"]) & asked)
        if score >= 1.0:
            scored.append((score, key, entry))
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    return [e for _, _, e in scored[:limit]]


def page_links(keys: Sequence[str], function: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for key in keys:
        page = pages().get(key)
        if page is None or not page.open_to(function) or any(o["page"] == key for o in out):
            continue
        out.append(link("help" if key == "help" else "page", key))
    return out[:MAX_LINKS]


REF_PAGES: Mapping[str, tuple[str, str, str]] = {
    "asset": ("map", "asset", "asset"),
    "zone": ("water", "zone", "zone"),
    "crew": ("crews", "crew", "crew"),
    "yard": ("crews", "yard", "yard"),
    "check": ("readiness", "check", "readiness"),
    "county": ("map", "county", "page"),
}


def reference_links(refs: Sequence[Mapping[str, str]], function: str) -> list[dict[str, str]]:
    """Deep links for the ids an answer names (its typed references): an asset on the map, a zone on the
    Water page, a crew or yard on Crews, a readiness check. Decisions keep their own chips (they need the
    proposal id the web resolves)."""
    out: list[dict[str, str]] = []
    for ref in refs:
        target = REF_PAGES.get(str(ref.get("kind")))
        if target is None:
            continue
        key, param, kind = target
        if not pages()[key].open_to(function):
            continue
        label = str(ref.get("label") or ref.get("id"))
        where = "on the map" if key == "map" else f"on the {pages()[key].label} page"
        extra = {"tab": "plan"} if param == "yard" else {}
        out.append(link(kind, key, f"{label} {where}", **{param: str(ref["id"])}, **extra))
    return out


def merge_links(*groups: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for group in groups:
        for item in group:
            if not any(o["href"] == item["href"] for o in out):
                out.append(dict(item))
    return out[:MAX_LINKS]


def write_glossary(path: Path = GLOSSARY_FILE) -> int:
    data = web_glossary()
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return len(data)


if __name__ == "__main__":
    sys.stdout.write(f"wrote {write_glossary()} terms to {GLOSSARY_FILE}\n")


MODEL_CARDS = Path(__file__).with_name("model_cards.yaml")


@lru_cache(maxsize=1)
def _cards() -> list[dict[str, Any]]:
    return list(yaml.safe_load(MODEL_CARDS.read_text(encoding="utf-8"))["cards"])


def _figure(key: str) -> str:
    from sgw.common.numbers import numbers

    e = numbers()[key]
    v = float(e.value)
    if e.unit == "recall":
        return f"{round(v * 100)}%"
    if e.unit == "%":
        return f"{v:g}%"
    return f"{round(v):,}" if v >= 100 else f"{v:g}"


def model_cards(text: str, topics: Sequence[str] = ()) -> list[dict[str, str]]:
    """The cards of the platform's own models the question names: method, inputs, provenance and quality with
    the figures of numbers.yaml filled in (R34; the eval reports behind them are cited there)."""
    flat = fold(" ".join([text, *topics]))
    out: list[dict[str, str]] = []
    for card in _cards():
        if any(fold(m) in flat for m in card["match"]):
            quality = re.sub(r"\{(\w+)\}", lambda m: _figure(m[1]), " ".join(card["quality"].split()))
            out.append({**card, "quality": quality})
    return out[:2]
