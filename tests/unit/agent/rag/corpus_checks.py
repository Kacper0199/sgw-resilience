"""Shared corpus checks: the documents and facts of evals/heldout/corpus_requirements.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from sgw.agent.rag.corpus import Document
from sgw.agent.rag.render import render

REPO = Path(__file__).resolve().parents[4]
REQUIREMENTS = REPO / "evals" / "heldout" / "corpus_requirements.yaml"
VALUE_RE = re.compile(r"[A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)+|\d+(?:[.,]\d+)*")


def requirements() -> dict[str, Any]:
    return yaml.safe_load(REQUIREMENTS.read_text(encoding="utf-8"))


def flat(text: str) -> str:
    text = re.sub(r"[|+=]{2,}|\|", " ", text)
    return " ".join(text.split())


def fact_values(fact: str) -> list[str]:
    """Ids and numbers a fact states; each must appear in the document's rendered text."""
    out = []
    for m in VALUE_RE.finditer(fact):
        v = m.group(0)
        if re.fullmatch(r"[A-Z]", v):
            continue
        out.append(v)
    return out


def find(docs: list[Document], req: dict[str, Any]) -> Document | None:
    for d in docs:
        if d.doc_id == req["doc_id"] and (d.revision or None) == (req.get("revision") or None):
            return d
    return None


def missing_values(doc: Document, fact: str) -> list[str]:
    text = flat(render(doc).text)
    joined = text.replace(" ", "")
    return [v for v in fact_values(fact) if v not in text and v.replace(" ", "") not in joined]
