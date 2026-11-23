"""Held-out evaluation material: manifest integrity, set sizes, item validity against contracts."""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from sgw.contracts.evidence import ALLOWED_DIGIT_PATTERNS, SLOT_RE, EvidenceRef, render, slots_in, verify_text
from sgw.contracts.tools import MODEL_VISIBLE_TOOLS, TOOLS
from sgw.contracts.vocab import DecisionStep, EvalSplit, Trust, UiSeverity

ROOT = Path(__file__).resolve().parents[2]
EVALS = ROOT / "evals"
SETS = ("extractor", "retrieval", "copilot", "narrate", "redteam", "judge")
HELDOUT_SIZES = {"extractor": 30, "retrieval": 30, "copilot": 12, "narrate": 10, "redteam": 23, "judge": 28}
DEV_MIN = {"extractor": 10, "retrieval": 10, "copilot": 4, "narrate": 4, "redteam": 6, "judge": 6}
ID_PREFIX = {
    "extractor": "EXT",
    "retrieval": "RET",
    "copilot": "COP",
    "narrate": "NAR",
    "redteam": "RT",
    "judge": "JDG",
}
CATEGORIES = {
    "line_down",
    "pole_broken",
    "tree_on_line",
    "transformer_damage",
    "road_blocked",
    "flooding",
    "generator_status",
    "fuel_level",
    "pressure_low",
    "pump_status",
    "outage_report",
    "safety_hazard",
    "crew_status",
    "water_quality",
    "telemetry_loss",
    "other",
}
POLARITY = {"asserted", "negated", "hedged"}
REDTEAM_CONDITIONS = {
    "no_tool_call",
    "no_unregistered_tool_call",
    "approval_state_unchanged",
    "run_tainted",
    "instructions_detected",
    "claims_exclude_quotes",
    "output_excludes",
    "canary_absent",
    "no_external_urls_in_output",
    "judge_criterion",
    "verifier_clean",
    "citations_valid",
    "marked_unverified",
    "context_excludes",
    "input_rejected_or_stale",
    "must_cite",
    "risk_unchanged",
}
BANNED = re.compile(r"company a\b|fictional|anonymous", re.IGNORECASE)


def _manifest() -> ModuleType:
    spec = importlib.util.spec_from_file_location("evals_manifest", EVALS / "manifest.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load(rel: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((EVALS / rel).read_text(encoding="utf-8"))
    return data


def _items(split: str, name: str) -> list[dict[str, Any]]:
    data = _load(f"{split}/{name}.yaml")
    assert data["set"] == name and data["split"] == split
    assert data["split"] in {e.value for e in EvalSplit}
    items: list[dict[str, Any]] = data["items"]
    return items


def _all(name: str) -> list[dict[str, Any]]:
    return _items("heldout", name) + _items("dev", name)


@pytest.fixture(scope="module")
def corpus() -> dict[str, Any]:
    return _load("heldout/corpus_requirements.yaml")


@pytest.fixture(scope="module")
def facts(corpus: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {f["id"]: (d["doc_id"], d.get("revision")) for d in corpus["documents"] for f in d["facts"]}


def test_manifest_matches_every_guarded_file() -> None:
    assert _manifest().problems() == []


def test_manifest_detects_a_changed_file(tmp_path: Path) -> None:
    m = _manifest()
    for rel in m.covered_paths():
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes((ROOT / rel).read_bytes())
    manifest = tmp_path / "evals" / "MANIFEST.sha256"
    manifest.write_bytes((EVALS / "MANIFEST.sha256").read_bytes())
    assert m.problems(tmp_path, manifest) == []
    target = tmp_path / "evals" / "heldout" / "judge.yaml"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    (tmp_path / "evals" / "heldout" / "extra.yaml").write_text("x: 1\n", encoding="utf-8")
    found = m.problems(tmp_path, manifest)
    assert "changed without manifest update: evals/heldout/judge.yaml" in found
    assert "not in manifest: evals/heldout/extra.yaml" in found


def test_manifest_pins_family_b_inputs() -> None:
    listed = _manifest().read()
    for rel in (
        "data/synthetic/family_b.yaml",
        "data/synthetic/family_b/debby_b.yaml",
        "data/synthetic/family_b/seeds.yaml",
    ):
        assert rel in listed


@pytest.mark.parametrize("name", SETS)
def test_heldout_counts_match_the_plan(name: str) -> None:
    assert len(_items("heldout", name)) == HELDOUT_SIZES[name]


@pytest.mark.parametrize("name", SETS)
def test_dev_split_exists_and_is_disjoint(name: str) -> None:
    dev, held = _items("dev", name), _items("heldout", name)
    assert len(dev) >= DEV_MIN[name]
    key = {"extractor": "text", "retrieval": "query", "redteam": "payload", "judge": "candidate"}.get(name)
    if key:
        assert not {i[key] for i in dev} & {i[key] for i in held}
    assert all(i["id"].startswith(f"{ID_PREFIX[name]}-D-") for i in dev)
    assert all(i["id"].startswith(f"{ID_PREFIX[name]}-H-") for i in held)


def test_ids_unique_across_all_sets() -> None:
    ids = [i["id"] for name in SETS for i in _all(name)]
    assert [k for k, v in Counter(ids).items() if v > 1] == []


def test_naming_rule_holds_in_every_eval_file() -> None:
    for rel in _manifest().covered_paths():
        if rel.startswith(("evals/", "data/synthetic/family_b/")) and not rel.endswith(".py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert not BANNED.search(text), rel


def test_extractor_items_are_well_formed() -> None:
    hostile = 0
    for it in _all("extractor"):
        assert it["trust"] in {t.value for t in Trust}
        assert it["expected"], it["id"]
        for c in it["expected"]:
            assert c["category"] in CATEGORIES, it["id"]
            assert c["polarity"] in POLARITY, it["id"]
            assert c["severity_hint"] in {s.value for s in UiSeverity}, it["id"]
            assert c["quote"] in it["text"], (it["id"], c["quote"])
            assert ("value" in c) == ("unit" in c), it["id"]
            assert set(c.get("category_alt", [])) <= CATEGORIES - {c["category"]}, it["id"]
        if it.get("hostile"):
            hostile += 1
            assert it["forbidden_quotes"], it["id"]
            assert all(q in it["text"] for q in it["forbidden_quotes"]), it["id"]
    assert hostile >= 6


def test_retrieval_items_cite_required_documents(facts: dict[str, tuple[str, str | None]]) -> None:
    for it in _all("retrieval"):
        assert it["relevant"], it["id"]
        for r in it["relevant"]:
            for f in r["facts"]:
                assert facts[f][0] == r["doc_id"], (it["id"], f)
                assert facts[f][1] == r.get("revision"), (it["id"], f)
    kinds = Counter(i["kind"] for i in _items("heldout", "retrieval"))
    assert kinds["superseded"] >= 5 and kinds["exact_id"] + kinds["legacy_id"] >= 4


def test_superseded_pairs_are_planted(corpus: dict[str, Any]) -> None:
    docs = corpus["documents"]
    superseded = [d for d in docs if d["status"] == "superseded"]
    assert len(superseded) == 6
    in_force = {(d["doc_id"], d.get("revision")) for d in docs if d["status"] == "in_force"}
    for d in superseded:
        newer = d["superseded_by"].split(" (")[0]
        doc_id, rev = newer.rsplit(" Rev ", 1)
        assert (doc_id, rev.split("/")[0]) in in_force, d["doc_id"]
    assert sum(1 for d in docs if d.get("hostile")) == 4
    assert any(d["status"] == "superseded" and d.get("change") for d in docs)


def test_copilot_tasks_use_contract_tools_and_three_unanswerable(
    corpus: dict[str, Any], facts: dict[str, tuple[str, str | None]]
) -> None:
    service_only = {n for n, (meta, _, _) in TOOLS.items() if not meta.model_visible}
    doc_ids = {d["doc_id"] for d in corpus["documents"]}
    unanswerable_topics = {u["id"] for u in corpus["must_not_mention"]}
    for split in ("heldout", "dev"):
        data = _load(f"{split}/copilot.yaml")
        assert set(data["forbidden_tools"]) == service_only
        for it in data["items"]:
            assert set(it["expected_tools"]) | set(it["allowed_extra_tools"]) <= set(MODEL_VISIBLE_TOOLS), it[
                "id"
            ]
            assert set(it["citations"]) <= doc_ids, it["id"]
            datetime.fromisoformat(it["as_of"].replace("Z", "+00:00"))
            if it["decision"]:
                assert it["decision"] in {d.value for d in DecisionStep}
            if not it["answerable"]:
                assert it["unanswerable_ref"] in unanswerable_topics, it["id"]
                assert it["citations"] == []
    held = _items("heldout", "copilot")
    assert sum(1 for i in held if not i["answerable"]) == 3


def test_copilot_truth_pointers_match_the_story_of_record() -> None:
    truth = json.loads((ROOT / "data/fixtures/helene/truth_table.json").read_text(encoding="utf-8"))
    hinge = next(c for c in truth["seeded_cases"] if c["id"] == "HINGE-PS17-N-N1")["outcome"]
    assert hinge["effective_decide_by_N_utc"] == "2024-09-27T05:44:00Z"
    assert hinge["effective_decide_by_N1_utc"] == "2024-09-27T04:28:00Z"
    assert hinge["effective_shift_min"] == -76.0
    assert hinge["no_regret_share_ppm"][0] < 800_000 <= hinge["no_regret_share_ppm"][1]
    assert truth["water"]["PS-17"]["below_floor_utc"] == "2024-09-27T10:05:00Z"
    assert truth["clocks_by_advisory"]["N+1"]["bound_by"]["DC-D3-PS17-FUEL"] == "DC-D3-PS17-POWER"


def test_narrate_references_pass_the_k15_verifier(corpus: dict[str, Any]) -> None:
    registry = _registry(corpus)
    for it in _all("narrate"):
        refs = {e["id"] for e in it["evidence"]}
        for e in it["evidence"]:
            EvidenceRef.model_validate(e)
        assert set(it["required_refs"]) <= refs, it["id"]
        ids = registry | {e["citation"] for e in it["evidence"]} | refs
        text = " ".join(" " if t.strip(".,;:()") in ids else t for t in it["reference_output"].split(" "))
        assert verify_text(text, refs) == [], it["id"]
        render(it["reference_output"], it["slot_values"])
        cited = [r for r, _ in slots_in(it["reference_output"])]
        assert set(it["required_refs"]) <= set(cited), it["id"]
        order = [cited.index(r) for r in it["required_order"]]
        assert order == sorted(order), it["id"]


def test_redteam_covers_the_injection_channels() -> None:
    held = _items("heldout", "redteam")
    channels = Counter(i["channel"] for i in held)
    assert channels["field_note"] >= 4 and channels["customer_ticket"] >= 3 and channels["nws_alert"] >= 3
    assert channels["document"] + channels["ocr"] >= 3
    for it in _all("redteam"):
        conds = it["pass_conditions"]
        assert set(conds) <= REDTEAM_CONDITIONS, it["id"]
        if "output_excludes" in conds:
            assert conds.get("judge_criterion"), it["id"]
    refs = Counter(i["sec_ref"] for i in held)
    assert refs["SEC-39"] >= 1 and refs["SEC-40"] >= 1
    assert any("citations_valid" in i["pass_conditions"] for i in held)
    dev_text = (EVALS / "dev" / "redteam.yaml").read_text(encoding="utf-8")
    for it in held:
        for c in it["pass_conditions"].get("canary_absent", []):
            assert c not in dev_text


def test_judge_labels_are_balanced_and_consistent() -> None:
    held = _items("heldout", "judge")
    clear = [i for i in held if "second_labeller" not in i]
    border = [i for i in held if "second_labeller" in i]
    assert Counter(i["label_pass"] for i in clear) == {True: 10, False: 10}
    assert len(border) >= 8 and all(i["second_labeller"] == "pending" for i in border)
    assert {i["label_score"] for i in border} <= {2, 3}
    for it in _all("judge"):
        assert it["label_pass"] == (it["label_score"] >= 3), it["id"]


def test_family_b_config_and_fault_truth_table() -> None:
    scenario = yaml.safe_load((ROOT / "data/synthetic/family_b/debby_b.yaml").read_text(encoding="utf-8"))
    seeds = yaml.safe_load((ROOT / "data/synthetic/family_b/seeds.yaml").read_text(encoding="utf-8"))
    faults = _load("heldout/family_b/fault_truth_table.yaml")
    assert scenario["family"] == "B" and seeds["family"] == "B"
    assert seeds["scenario_seed"] == scenario["seed"] == seeds["replicate_seeds"][0]
    assert len(set(seeds["replicate_seeds"])) == len(seeds["replicate_seeds"])
    seeded = {c["id"] for c in scenario["seeded"]}
    assert {f["id"] for f in faults["faults"]} <= seeded
    window = faults["telemetry_window"]
    days = (
        datetime.fromisoformat(window["end_utc"].replace("Z", "+00:00"))
        - datetime.fromisoformat(window["start_utc"].replace("Z", "+00:00"))
    ).total_seconds() / 86400
    assert faults["device_days"] == pytest.approx(days * len(faults["monitored_devices"]))
    devices = {d["device_id"] for d in faults["monitored_devices"]}
    for f in faults["faults"]:
        assert set(f["devices"]) & devices, f["id"]
        assert f["onset_utc"] < f["detect_by_utc"] <= f["end_utc"], f["id"]
    generated = json.loads(
        (EVALS / "heldout/family_b/truth_table.generated.json").read_text(encoding="utf-8")
    )
    assert generated["family"] == "B" and generated["seed"] == scenario["seed"]


def _utc(text: str) -> datetime:
    value = str(text)
    if "T" not in value:
        value += "T00:00:00Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _in_force(corpus: dict[str, Any], doc_id: str, revision: str | None, as_of: datetime) -> bool:
    revs = [d for d in corpus["documents"] if d["doc_id"] == doc_id and _utc(d["effective"]) <= as_of]
    if not revs:
        return False
    latest = max(revs, key=lambda d: _utc(d["effective"]))
    if latest.get("expires") and _utc(latest["expires"]) <= as_of:
        return False
    return bool(latest.get("revision") == revision)


def test_items_expect_only_revisions_in_force_at_as_of(corpus: dict[str, Any]) -> None:
    for split in ("heldout", "dev"):
        data = _load(f"{split}/retrieval.yaml")
        for it in data["items"]:
            as_of = _utc(it.get("as_of", data["default_as_of"]))
            for r in it["relevant"]:
                assert _in_force(corpus, r["doc_id"], r.get("revision"), as_of), (it["id"], r["doc_id"])
            for r in it.get("must_not_retrieve", []):
                assert not _in_force(corpus, r["doc_id"], r.get("revision"), as_of), (it["id"], r["doc_id"])
    for it in _all("copilot"):
        as_of = _utc(it["as_of"])
        for doc_id in it["citations"]:
            revisions = [d.get("revision") for d in corpus["documents"] if d["doc_id"] == doc_id]
            assert any(_in_force(corpus, doc_id, r, as_of) for r in revisions), (it["id"], doc_id)
    for it in _all("narrate"):
        assert all(_utc(e["as_of"]) <= _utc(it["as_of"]) for e in it["evidence"]), it["id"]


def _registry(corpus: dict[str, Any]) -> set[str]:
    text = (ROOT / "data/fixtures/helene/network.json").read_text(encoding="utf-8")
    text += (ROOT / "data/synthetic/helene.yaml").read_text(encoding="utf-8")
    ids = set(re.findall(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+", text))
    return ids | {d["doc_id"] for d in corpus["documents"]}


def test_narrate_references_follow_the_d073_digit_rule(corpus: dict[str, Any]) -> None:
    registry = _registry(corpus)
    patterns = [p for p in ALLOWED_DIGIT_PATTERNS if "PS-17" not in p.pattern]
    for it in _all("narrate"):
        bundle = {e["citation"] for e in it["evidence"]} | {e["id"] for e in it["evidence"]}
        text = SLOT_RE.sub(" ", it["reference_output"])
        for token in re.findall(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+", text):
            if any(ch.isdigit() for ch in token) and (token in registry or token in bundle):
                text = text.replace(token, " ")
        for p in patterns:
            text = p.sub(" ", text)
        assert not re.search(r"\d", text), (it["id"], text)


def test_fault_windows_do_not_overlap_physical_events() -> None:
    faults = _load("heldout/family_b/fault_truth_table.yaml")
    for f in faults["faults"]:
        lo = _utc(f["onset_utc"]).timestamp() - 900
        hi = _utc(f["end_utc"]).timestamp() + 3600
        for ev in faults["physical_events"]:
            if set(f["devices"]) & set(ev["devices"]):
                apart = hi <= _utc(ev["from_utc"]).timestamp() or _utc(ev["to_utc"]).timestamp() <= lo
                assert apart, (f["id"], ev["id"])
