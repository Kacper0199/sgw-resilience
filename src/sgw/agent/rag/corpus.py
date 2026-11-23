"""Corpus documents: source loading, metadata model and the in-force rule.

A revision is in force at `as_of` when it is effective on or before `as_of`, no later revision of the same
document is effective on or before `as_of`, and its expiry (if any) is after `as_of` (evals/README.md). The
`status` field is the document's state today and is never used to decide what was in force at a scenario time.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = REPO_ROOT / "data" / "corpus"
SOURCE_DIRS = ("src/core", "src/extra", "src/federal", "generated")
FRONT_MATTER_RE = re.compile(r"\A---\n(?P<meta>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
REVISION_LETTERS = "ABCDEFGHJKLMNPRTUVWXYZ"

CLASSIFICATION_CODES = {
    "Public": "C0",
    "SGW Internal - Controlled": "C1",
    "SGW Restricted - Operations": "C2",
}
OWNER_MANUALS = {
    "GEP": "Emergency Management",
    "DOM": "Distribution Operations",
    "TSO": "Transmission & Substation",
    "WDS": "Water Distribution & Supply",
    "WQC": "Water Quality & Compliance",
    "MAL": "Mutual Assistance & Logistics",
    "PCN": "Corporate Communications",
}


class CorpusError(ValueError):
    pass


LOCAL_TZ = ZoneInfo("America/New_York")


def as_utc(value: date | datetime) -> datetime:
    """A document date takes effect at local midnight in the service area (Eastern: 04:00 or 05:00 UTC)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.combine(value, time(0, 0), tzinfo=LOCAL_TZ).astimezone(UTC)


@dataclass(frozen=True)
class Approval:
    function: str
    position: str
    name: str
    date: date


@dataclass(frozen=True)
class ChangeRow:
    rev: str
    date: date
    section: str
    change: str


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    family: str
    layout: str
    owner_function: str
    effective: date
    classification: str
    trust: str
    status: str
    body: str
    origin: str
    source_path: str
    revision: str | None = None
    change: int | None = None
    legacy_id: str | None = None
    sme: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None
    expires: date | None = None
    next_review: date | None = None
    approvals: tuple[Approval, ...] = ()
    changes: tuple[ChangeRow, ...] = ()
    decisions: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    licence: str = "SGW internal"
    source_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return self.revision or "issued"

    @property
    def version_id(self) -> str:
        return f"{self.doc_id}@{self.version}"

    @property
    def revision_label(self) -> str | None:
        if not self.revision:
            return None
        return f"{self.revision}/{self.change}" if self.change else self.revision

    @property
    def citation_id(self) -> str:
        label = self.revision_label
        return f"{self.doc_id} Rev {label}" if label else self.doc_id

    @property
    def class_code(self) -> str:
        try:
            return CLASSIFICATION_CODES[self.classification]
        except KeyError as exc:
            raise CorpusError(f"{self.doc_id}: unknown classification {self.classification!r}") from exc

    @property
    def effective_at(self) -> datetime:
        return as_utc(self.effective)

    @property
    def expires_at(self) -> datetime | None:
        return as_utc(self.expires) if self.expires else None

    @property
    def manual(self) -> str | None:
        code = self.doc_id.split(" ", 1)[0]
        return code if code in OWNER_MANUALS else None

    @property
    def slug(self) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", self.doc_id.lower()).strip("-")
        return f"{base}-rev-{self.revision.lower()}" if self.revision else base


def _date(value: Any, key: str, path: Path) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CorpusError(f"{path.name}: {key} is not a date: {value!r}") from exc


def _required_date(value: Any, key: str, path: Path) -> date:
    out = _date(value, key, path)
    if out is None:
        raise CorpusError(f"{path.name}: {key} is required")
    return out


def parse_document(text: str, path: Path, origin: str) -> Document:
    m = FRONT_MATTER_RE.match(text.replace("\r\n", "\n"))
    if not m:
        raise CorpusError(f"{path.name}: no front matter")
    meta = yaml.safe_load(m["meta"]) or {}
    if not isinstance(meta, dict):
        raise CorpusError(f"{path.name}: front matter is not a mapping")
    for key in ("doc_id", "title", "family", "effective"):
        if not meta.get(key):
            raise CorpusError(f"{path.name}: {key} is required")
    revision = meta.get("revision")
    if revision is not None:
        revision = str(revision)
        if revision not in REVISION_LETTERS:
            raise CorpusError(f"{path.name}: revision {revision!r} is not a letter from {REVISION_LETTERS}")
    approvals = tuple(
        Approval(
            function=str(a.get("function", "")),
            position=str(a.get("position", "")),
            name=str(a.get("name", "")),
            date=_required_date(a.get("date"), "approvals.date", path),
        )
        for a in meta.get("approvals") or []
    )
    changes = tuple(
        ChangeRow(
            rev=str(c.get("rev", "")),
            date=_required_date(c.get("date"), "changes.date", path),
            section=str(c.get("section", "")),
            change=str(c.get("change", "")),
        )
        for c in meta.get("changes") or []
    )
    family = str(meta["family"])
    record_families = {
        "form_record",
        "notice_issued",
        "switching_order",
        "inspection",
        "sitrep",
        "aar",
    }
    layout = str(meta.get("layout") or ("record" if family in record_families else "controlled"))
    known = {
        "doc_id", "legacy_id", "title", "family", "layout", "owner_function", "sme", "revision", "change",
        "effective", "supersedes", "superseded_by", "expires", "next_review", "approvals", "classification",
        "trust", "status", "decisions", "states", "changes", "licence", "source_url",
    }  # fmt: skip
    change = meta.get("change")
    return Document(
        doc_id=str(meta["doc_id"]).strip(),
        title=str(meta["title"]).strip(),
        family=family,
        layout=layout,
        owner_function=str(meta.get("owner_function") or "command"),
        effective=_required_date(meta["effective"], "effective", path),
        classification=str(meta.get("classification") or "SGW Internal - Controlled"),
        trust=str(meta.get("trust") or "verified_internal"),
        status=str(meta.get("status") or "in_force"),
        body=m["body"].strip("\n") + "\n",
        origin=origin,
        source_path=str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path),
        revision=revision,
        change=int(change) if change not in (None, "", 0) else None,
        legacy_id=str(meta["legacy_id"]) if meta.get("legacy_id") else None,
        sme=str(meta["sme"]) if meta.get("sme") else None,
        supersedes=str(meta["supersedes"]) if meta.get("supersedes") else None,
        superseded_by=str(meta["superseded_by"]) if meta.get("superseded_by") else None,
        expires=_date(meta.get("expires"), "expires", path),
        next_review=_date(meta.get("next_review"), "next_review", path),
        approvals=approvals,
        changes=changes,
        decisions=tuple(str(d) for d in meta.get("decisions") or []),
        states=tuple(str(s) for s in meta.get("states") or []),
        licence=str(meta.get("licence") or "SGW internal"),
        source_url=str(meta["source_url"]) if meta.get("source_url") else None,
        extra={k: v for k, v in meta.items() if k not in known},
    )


def load_corpus(root: Path = CORPUS_DIR) -> list[Document]:
    docs: list[Document] = []
    for sub in SOURCE_DIRS:
        folder = root / sub
        if not folder.is_dir():
            continue
        origin = sub.split("/")[-1]
        for path in sorted(folder.glob("*.md")):
            docs.append(parse_document(path.read_text(encoding="utf-8"), path, origin))
    check_unique(docs)
    return docs


def check_unique(docs: Iterable[Document]) -> None:
    seen: dict[str, str] = {}
    for d in docs:
        if d.version_id in seen:
            raise CorpusError(f"duplicate {d.version_id}: {seen[d.version_id]} and {d.source_path}")
        seen[d.version_id] = d.source_path


def in_force(docs: Sequence[Document], as_of: datetime) -> list[Document]:
    """The revisions in force at `as_of`, one per doc_id at most."""
    best: dict[str, Document] = {}
    for d in docs:
        if d.effective_at > as_of:
            continue
        cur = best.get(d.doc_id)
        if cur is None or d.effective_at > cur.effective_at:
            best[d.doc_id] = d
    return [d for d in best.values() if d.expires_at is None or d.expires_at > as_of]


def is_in_force(doc: Document, docs: Sequence[Document], as_of: datetime) -> bool:
    return any(d.version_id == doc.version_id for d in in_force(docs, as_of))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
