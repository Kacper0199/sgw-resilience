"""CV review queue: policy maths, seeded-case linking, committed artefacts, honest metrics."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any

import pytest

from sgw.contracts.eval_report import EvalReport
from sgw.models.cv import queue as q

ART = q.ARTEFACTS
LABELS = [
    "bridges_any",
    "buildings_any",
    "buildings_affected_or_greater",
    "buildings_minor_or_greater",
    "debris_any",
    "flooding_any",
    "flooding_structures",
    "roads_any",
    "roads_damage",
    "trees_any",
    "trees_damage",
    "water_any",
]


def _labels(**on: int) -> dict[str, int]:
    return {k: int(on.get(k, 0)) for k in LABELS}


def _probs(**p: float) -> dict[str, float]:
    return {k: float(p.get(k, 0.0)) for k in LABELS}


def _truth(*cases: tuple[str, str, Any]) -> dict[str, Any]:
    seeded = []
    for case_id, section, state in cases:
        seeded.append({"id": case_id, "outcome": {"damage_state": state, "section": section}})
    seeded.append({"id": "FAULT-NOT-DAMAGE", "outcome": {"duration_h": 2}})
    seeded.append(
        {"id": "FEEDER-NESTED", "outcome": {"feeder": {"damage_state": "complete", "section": "S-NEST"}}}
    )
    return {"seeded_cases": seeded}


def _policy(per_case: int) -> dict[str, Any]:
    pol = copy.deepcopy(q.policy())
    pol["seeded_case_photos"]["photos_per_case"] = per_case
    return pol


def _image(row: int, **labels: int) -> dict[str, Any]:
    return {
        "image_id": f"img-{row:04d}",
        "row_idx": row,
        "file": f"test_{row:04d}.jpg",
        "sha256": f"{row:064x}",
        "source_url": f"https://example.invalid/{row}",
        "cap_labels": _labels(**labels),
    }


def test_triage_score_is_weighted_mean_and_ignores_roads_damage() -> None:
    weights = q.policy()["triage_weights"]["values"]
    full = q.triage_score(_probs(**dict.fromkeys(weights, 1.0)))
    assert full == pytest.approx(1.0)
    assert q.triage_score(_probs()) == 0.0
    assert q.triage_score(_probs(roads_damage=1.0)) == 0.0
    assert q.triage_score(_probs(buildings_any=1.0, trees_any=1.0, water_any=1.0)) == 0.0
    more = q.triage_score(_probs(trees_damage=0.9, debris_any=0.9))
    less = q.triage_score(_probs(trees_damage=0.9))
    assert more > less > 0


def test_signals_actions_and_human_only_flags() -> None:
    probs = _probs(trees_damage=0.8, flooding_any=0.6, roads_damage=0.7, buildings_any=0.99, debris_any=0.3)
    sig = q.signals(probs)
    assert sig == ["trees_damage", "roads_damage", "flooding_any"]
    assert q.suggested_actions(sig) == ["line-clearance crew", "access check (routing penalty)"]
    assert q.human_only_flags(sig) == ["road damage, human review only"]


def test_seeded_damage_cases_read_direct_nested_and_numeric_states() -> None:
    cases = q.seeded_damage_cases(_truth(("A", "S-A", "slight"), ("B", "S-B", 3)))
    assert [(c.case_id, c.damage_state) for c in cases] == [
        ("FEEDER-NESTED", "complete"),
        ("B", "extensive"),
        ("A", "slight"),
    ]


def test_linking_uses_cap_labels_only_and_is_deterministic() -> None:
    sample = {
        "images": [
            _image(9, trees_damage=1),
            _image(3, trees_damage=1, debris_any=1),
            _image(5, trees_damage=1),
            _image(7, flooding_any=1, trees_damage=1, debris_any=1),
        ]
    }
    cases = q.seeded_damage_cases(
        {
            "seeded_cases": [
                {"id": "S1", "outcome": {"damage_state": "slight", "section": "X1"}},
                {"id": "S2", "outcome": {"damage_state": "slight", "section": "X2"}},
                {"id": "M-FLOOD", "outcome": {"damage_state": "moderate", "section": "X3"}},
            ]
        }
    )
    pol = _policy(1)
    links = q.link_seeded_cases(cases, sample, pol)
    assert {k: v.case_id for k, v in links.items()} == {
        "img-0007": "M-FLOOD",
        "img-0005": "S1",
        "img-0009": "S2",
    }
    assert q.link_seeded_cases(cases, sample, pol) == links
    two = q.link_seeded_cases(cases[1:2], sample, _policy(2))
    assert sorted(two) == ["img-0005", "img-0009"]


def test_linking_fails_loudly_without_a_fitting_photo() -> None:
    truth = {"seeded_cases": [{"id": "C", "outcome": {"damage_state": 4, "section": "S"}}]}
    cases = q.seeded_damage_cases(truth)
    with pytest.raises(ValueError, match="no photo set"):
        q.link_seeded_cases(cases, {"images": [_image(1, trees_damage=1)]}, _policy(1))


def test_build_queue_orders_by_score_and_rejects_foreign_scores() -> None:
    sample = {
        "images": [
            _image(1, trees_damage=1),
            _image(2, buildings_affected_or_greater=1, debris_any=1, trees_damage=1),
            _image(3),
        ]
    }
    truth = _truth(("SLIGHT", "S-1", "slight"))
    truth["seeded_cases"] = truth["seeded_cases"][:2]
    scores = {
        "model_id": "m-reference",
        "model_revision": "r",
        "items": [
            {"image_id": "img-0001", "image_sha256": f"{1:064x}", "probs": _probs(trees_damage=0.9)},
            {"image_id": "img-0002", "image_sha256": f"{2:064x}", "probs": _probs(trees_damage=0.2)},
            {"image_id": "img-0003", "image_sha256": f"{3:064x}", "probs": _probs()},
        ],
    }
    pol = _policy(1)
    queue = q.build_queue(scores, sample, truth, pol)
    assert [r["image_id"] for r in queue["rows"]] == ["img-0001", "img-0002", "img-0003"]
    assert [r["rank"] for r in queue["rows"]] == [1, 2, 3]
    assert queue["rows"][0]["seeded_case_id"] == "SLIGHT"
    assert queue["rows"][2]["no_damage_control"] is True
    assert all(r["status"] == "awaiting_review" for r in queue["rows"])
    assert queue["cases"] == [
        {
            "case_id": "SLIGHT",
            "section_id": "S-1",
            "damage_state": "slight",
            "case_score": queue["rows"][0]["triage_score"],
            "photo_ids": ["img-0001"],
            "photo_ranks": [1],
            "status": "awaiting_review",
            "case_rank": 1,
        }
    ]
    assert queue["seeded_order"]["tier_violations"] == 0
    scores["items"][0]["image_sha256"] = "0" * 64 + "x"
    with pytest.raises(ValueError, match="different file"):
        q.build_queue(scores, sample, truth, pol)


def test_tier_check_counts_a_slight_case_above_a_structural_case() -> None:
    pol = _policy(1)
    case_rows = [
        {"case_id": "S", "damage_state": "slight", "case_score": 0.5, "case_rank": 1},
        {"case_id": "C", "damage_state": "complete", "case_score": 0.4, "case_rank": 2},
    ]
    rows = [{"no_damage_control": True, "row_idx": 1, "triage_score": 0.45}]
    order = q.seeded_order(case_rows, rows, pol)
    assert order["tier_violations"] == 1
    assert order["ladder_discordant_pairs"] == 1
    assert order["structural_above_all_control_groups"] is False


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return dict(q.load_json(ART / "manifest.json"))


def test_manifest_pins_reference_model_licences_and_hashes(manifest: dict[str, Any]) -> None:
    model = manifest["model"]
    assert model["id"] == "MITLL/LADI-v2-classifier-small-reference"
    assert len(model["revision"]) == 40
    assert model["licence"] == "MIT"
    assert len(model["weights_sha256"]) == 64
    assert manifest["dataset"]["licence"] == "CC-BY-4.0"
    assert manifest["dataset"]["n_scored"] == 200
    assert manifest["runtime"]["device"] == "mps"
    assert manifest["runtime"]["warm_s_per_image_p50"] > 0


def test_committed_artefacts_verify_clean() -> None:
    assert q.verify() == []


def test_queue_orders_the_seeded_damage_cases() -> None:
    queue = q.load_json(ART / "review_queue.json")
    order = queue["seeded_order"]
    truth_cases = q.seeded_damage_cases(q.load_json(q.TRUTH_TABLE))
    assert {c["case_id"] for c in queue["cases"]} == {c.case_id for c in truth_cases}
    assert len(queue["cases"]) == 6
    per_case = q.policy()["seeded_case_photos"]["photos_per_case"]
    assert all(len(c["photo_ids"]) == per_case for c in queue["cases"])
    assert [c["case_rank"] for c in queue["cases"]] == list(range(1, 7))
    scores = [c["case_score"] for c in queue["cases"]]
    assert scores == sorted(scores, reverse=True)
    assert order["tier_violations"] == 0
    assert order["structural_above_all_control_groups"] is True
    assert order["structural_min_score"] > order["control_group_max_score"]
    states = [c["damage_state"] for c in queue["cases"]]
    assert states[-2:] == ["slight", "slight"]


def test_artefacts_disclose_the_acceptance_history_and_the_honest_miss(manifest: dict[str, Any]) -> None:
    queue = q.load_json(ART / "review_queue.json")
    history = " ".join(queue["acceptance_history"])
    for phrase in ("single-photo design failed", "5 of 13", "k=1, 3 and 5", "two tiers", "k=5 chosen"):
        assert phrase in history
    assert queue["honest_miss"] == "D2 complete ranks 4th of 4 damaged cases"
    assert manifest["acceptance_history"] == queue["acceptance_history"]
    assert manifest["honest_miss"] == queue["honest_miss"]
    assert manifest["review_queue_sha256"] == q.sha256_file(ART / "review_queue.json")


def test_honest_miss_names_the_most_severe_case_and_its_place() -> None:
    pol = _policy(1)
    case_rows = [
        {"case_id": "M1-X", "damage_state": "moderate", "case_rank": 1},
        {"case_id": "C1-Y", "damage_state": "complete", "case_rank": 2},
        {"case_id": "S1-Z", "damage_state": "slight", "case_rank": 3},
    ]
    assert q.honest_miss(case_rows, pol) == "C1 complete ranks 2nd of 2 damaged cases"


def test_queue_rows_carry_the_human_in_the_loop_framing() -> None:
    queue = q.load_json(ART / "review_queue.json")
    assert "not SGW territory" in queue["imagery_note"]
    assert "reviewer confirms" in queue["review_note"]
    assert len(queue["rows"]) == 200
    for row in queue["rows"]:
        if "roads_damage" in row["signals"]:
            assert row["human_only"]
    rows = list(csv.DictReader((ART / "review_queue.csv").open(encoding="utf-8")))
    assert [r["image_id"] for r in rows] == [r["image_id"] for r in queue["rows"]]


def test_only_published_reference_values_are_quoted() -> None:
    report = EvalReport.model_validate(q.load_json(ART / "ladi_reference_eval.json"))
    assert {m.split for m in report.metrics} == {"ladi_reference"}
    assert all(m.label == "F" for m in report.metrics)
    quoted = {(r["split"], r["value"]) for r in q.REFERENCE_MAP["rows"]}
    assert quoted == {("test", 91.1), ("validation", 93.3)}
    assert {m.value for m in report.metrics} == {v for _, v in quoted}
    text = "".join(p.read_text(encoding="utf-8") for p in ART.glob("*.json") if p.name != "sample.json")
    assert '"ap"' not in text and "macro_ap" not in text


def test_every_thumbnail_has_a_provenance_line_and_repo_stays_small(manifest: dict[str, Any]) -> None:
    rows = list(csv.DictReader((ART / "thumbs" / "PROVENANCE.csv").open(encoding="utf-8")))
    files = sorted(p.name for p in (ART / "thumbs").glob("*.jpg"))
    assert sorted(Path(r["file"]).name for r in rows) == files
    assert all(r["licence"] == "CC-BY-4.0" and r["source_sha256"] for r in rows)
    total = sum(p.stat().st_size for p in ART.rglob("*") if p.is_file())
    assert total < 4 * 1024 * 1024
    assert manifest["thumbnails"]["count"] == len(files)
    attribution = (ART.parents[1] / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "data/artefacts/cv/thumbs/" in attribution
    assert "LADI-v2-classifier-small-reference" in attribution


def test_sample_json_is_well_formed() -> None:
    sample = json.loads((ART / "sample.json").read_text(encoding="utf-8"))
    assert sample["licence"] == "CC-BY-4.0"
    assert len(sample["images"]) == 200
    assert len({i["row_idx"] for i in sample["images"]}) == 200
    assert all(len(i["sha256"]) == 64 for i in sample["images"])
