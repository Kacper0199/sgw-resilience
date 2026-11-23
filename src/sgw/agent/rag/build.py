"""Corpus build: run the template generator, render every document and write `MANIFEST.yaml`. `check=True`
reports drift instead of writing (used by tests and CI)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from sgw.agent.rag.corpus import CORPUS_DIR, Document, load_corpus, sha256_text
from sgw.agent.rag.generator import generate
from sgw.agent.rag.render import render

MANIFEST = CORPUS_DIR / "MANIFEST.yaml"
RENDERED = CORPUS_DIR / "rendered"


def manifest_row(doc: Document, rendered_text: str, rendered_path: Path) -> dict[str, Any]:
    return {
        "doc_id": doc.doc_id,
        "revision": doc.revision_label,
        "citation_id": doc.citation_id,
        "status": doc.status,
        "effective": doc.effective.isoformat(),
        "expires": doc.expires.isoformat() if doc.expires else None,
        "family": doc.family,
        "origin": doc.origin,
        "classification": doc.classification,
        "trust": doc.trust,
        "synthetic": doc.origin != "federal",
        "licence": doc.licence,
        "source": doc.source_url or doc.source_path,
        "rendered": str(rendered_path.relative_to(CORPUS_DIR)),
        "sha256": sha256_text(rendered_text),
    }


def expected_outputs(root: Path = CORPUS_DIR) -> dict[Path, str]:
    out: dict[Path, str] = {root / "generated" / g.file_name: g.source() for g in generate()}
    return out


def build(root: Path = CORPUS_DIR, *, check: bool = False) -> dict[str, Any]:
    drift: list[str] = []
    for path, text in expected_outputs(root).items():
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            drift.append(str(path.relative_to(root)))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    docs = load_corpus(root)
    rows = []
    expected_rendered: set[Path] = set()
    for doc in docs:
        text = render(doc).text
        path = root / "rendered" / f"{doc.slug}.txt"
        expected_rendered.add(path)
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            drift.append(str(path.relative_to(root)))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        rows.append(manifest_row(doc, text, path))
    stale = [p for p in (root / "rendered").glob("*.txt") if p not in expected_rendered]
    for p in stale:
        drift.append(str(p.relative_to(root)))
        if not check:
            p.unlink()
    rows.sort(key=lambda r: (r["doc_id"], r["revision"] or ""))
    sgw = [r for r in rows if r["synthetic"]]
    manifest = {
        "version": 1,
        "note": (
            "SGW documents are synthetic, written for this platform (hand-written and template-generated); "
            "federal documents are US government works reproduced from the listed sources."
        ),
        "counts": {
            "documents_sgw": len(sgw),
            "documents_federal": len(rows) - len(sgw),
            "by_family": dict(sorted(Counter(r["family"] for r in sgw).items())),
            "by_origin": dict(sorted(Counter(r["origin"] for r in rows).items())),
            "superseded_revisions": sum(1 for r in rows if r["status"] == "superseded"),
        },
        "documents": rows,
    }
    text = yaml.safe_dump(manifest, sort_keys=False, width=200)
    if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != text:
        drift.append("MANIFEST.yaml")
        if not check:
            (root / "MANIFEST.yaml").write_text(text, encoding="utf-8")
    return {"documents": len(rows), "drift": drift, "counts": manifest["counts"]}
