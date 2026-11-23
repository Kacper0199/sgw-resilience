"""Corpus contract: 120 SGW documents in house style, the six superseded pairs, the four hostile records,
every fact of evals/heldout/corpus_requirements.yaml, nothing on the unanswerable topics, no drift."""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime

import pytest

from sgw.agent.rag.build import build
from sgw.agent.rag.corpus import REVISION_LETTERS, Document, in_force, is_in_force, load_corpus
from sgw.agent.rag.render import UNCONTROLLED, render, superseded_line

from .corpus_checks import find, missing_values, requirements

BANNED = re.compile(
    r"fictional|synthetic|anonymous|\bcompany a\b|\bacme\b|riverside|springfield|john smith|\bmain st\b",
    re.IGNORECASE,
)
UNANSWERABLE = re.compile(
    r"public safety power shut|\bPSPS\b|docket|cost recovery|storm[- ]cost|\brider\b"
    r"|vegetation management budget|relative humidity|red flag warning",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def docs() -> list[Document]:
    return load_corpus()


def _sgw(docs: list[Document]) -> list[Document]:
    return [d for d in docs if d.origin != "federal"]


def test_corpus_mix_matches_the_plan(docs: list[Document]) -> None:
    sgw = _sgw(docs)
    assert len(sgw) == 120
    assert Counter(d.origin for d in sgw) == {"core": 36, "extra": 43, "generated": 41}
    assert sum(1 for d in sgw if d.status == "superseded") == 6
    assert len([d for d in docs if d.origin == "federal"]) >= 3
    assert all(d.licence.startswith("US federal government work") for d in docs if d.origin == "federal")


def test_every_required_document_and_fact_is_present(docs: list[Document]) -> None:
    problems = []
    for req in requirements()["documents"]:
        doc = find(docs, req)
        if doc is None:
            problems.append(f"{req['key']} missing")
            continue
        for key, actual in (("status", doc.status), ("effective", str(doc.effective))):
            if str(req[key]) != actual:
                problems.append(f"{req['key']} {key} {actual}")
        if req.get("change") != doc.change:
            problems.append(f"{req['key']} change {doc.change}")
        if req.get("legacy_id") and req["legacy_id"] != doc.legacy_id:
            problems.append(f"{req['key']} legacy {doc.legacy_id}")
        if req.get("expires") and str(req["expires"]) != str(doc.expires):
            problems.append(f"{req['key']} expires {doc.expires}")
        if doc.class_code not in ("C0", "C1"):
            problems.append(f"{req['key']} class {doc.class_code} is not searchable")
        problems += [f"{f['id']} lacks {v}" for f in req["facts"] for v in missing_values(doc, f["text"])]
    assert problems == []


def test_superseded_pairs_differ_and_say_so(docs: list[Document]) -> None:
    old = [d for d in docs if d.status == "superseded"]
    assert len(old) == 6
    for d in old:
        line = superseded_line(d)
        assert line and line in render(d).text
        newer = [n for n in docs if n.doc_id == d.doc_id and n.effective > d.effective]
        assert len(newer) == 1 and newer[0].status == "in_force"
        assert newer[0].changes, f"{newer[0].citation_id} has no Revision Summary row"
    assert any(d.change for d in old), "one old revision must carry a Chg number"


def test_house_style_markers(docs: list[Document]) -> None:
    for d in _sgw(docs):
        text = render(d).text
        assert not BANNED.search(text.replace("altamaha-fuel-portal.example", "")), d.citation_id
        assert re.search(r"Page 1 of \d+", text), d.citation_id
        if d.layout == "controlled":
            assert UNCONTROLLED in text and (d.revision or "A") in REVISION_LETTERS, d.citation_id
            assert "*" not in d.body and "`" not in d.body, d.citation_id


def test_no_document_mentions_an_unanswerable_topic(docs: list[Document]) -> None:
    hits = {d.citation_id: m.group(0) for d in docs if (m := UNANSWERABLE.search(render(d).text))}
    assert hits == {}


def test_hostile_records_look_like_ordinary_records(docs: list[Document]) -> None:
    hostile = [r for r in requirements()["documents"] if r.get("hostile")]
    assert len(hostile) == 4
    for req in hostile:
        doc = find(docs, req)
        assert doc is not None and doc.layout == "record" and doc.trust in ("internal_free_text", "external")


def test_in_force_rule_follows_dates_not_status(docs: list[Document]) -> None:
    def rev(doc_id: str, at: str) -> str | None:
        live = [
            d for d in in_force(docs, datetime.fromisoformat(at).replace(tzinfo=UTC)) if d.doc_id == doc_id
        ]
        return live[0].version if live else None

    assert rev("DOM 14.206", "2024-09-27") == "K"
    assert rev("DOM 14.206", "2023-06-15") == "J"
    assert rev("WQC 07.114", "2023-01-01") == "D"
    assert rev("GEP 2H.01", "2024-09-16T03:59") == "E"
    assert rev("GEP 2H.01", "2024-09-16T04:00") == "F"
    assert rev("OB-24-07", "2024-10-15T03:59") == "issued"
    assert rev("OB-24-07", "2024-10-15T04:00") is None
    assert rev("AAR-HEL-24", "2024-09-27") is None
    old = next(d for d in docs if d.doc_id == "WDS 03.322" and d.revision == "B")
    assert old.status == "superseded" and is_in_force(old, docs, datetime(2023, 3, 1, tzinfo=UTC))


def test_rendered_files_and_manifest_have_no_drift() -> None:
    result = build(check=True)
    assert result["drift"] == []
