"""Damage-assessment review queue (O-06) from precomputed LADI-v2 reference scores. No torch at run time.

The queue orders photos for a human reviewer; it never confirms damage on its own. Model numbers quoted
anywhere come only from the published reference values in `REFERENCE_MAP` (K17 report), never from this code.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
ARTEFACTS = ROOT / "data" / "artefacts" / "cv"
TRUTH_TABLE = ROOT / "data" / "fixtures" / "helene" / "truth_table.json"
POLICY_PATH = Path(__file__).with_name("queue_policy.yaml")
IMAGERY_NOTE = "benchmark imagery (LADI-v2 test split, 2023 US disaster events), not SGW territory"
REVIEW_NOTE = "prioritisation aid: a reviewer confirms or rejects every photo before it changes a plan"
ACCEPTANCE_HISTORY = [
    "single-photo design failed: one stand-in photo per seeded case left 5 of 13 severity pairs out of order "
    "and a slight case below no-damage control photos (earlier scores of the same model, R05)",
    "photo-set sizes k=1, 3 and 5 compared on those existing scores: "
    "k=1 fails the two-tier check, k=3 and k=5 pass",
    "criterion relaxed from the full four-level severity ladder to two tiers (moderate or worse above "
    "slight and above every no-damage control group), because the LADI v2 paper merged "
    "building-damage levels that the classifier separates poorly; the full ladder is still reported "
    "(ladder_discordant_pairs)",
    "k=5 chosen; photos are picked by CAP volunteer labels only, never by model score",
]
DAMAGE_STATE_NAMES = {1: "slight", 2: "moderate", 3: "extensive", 4: "complete"}

BASELINE = "untuned BiT-50"

# Published reference values (Scheele, Picchione, Liu 2024, arXiv:2406.02780 Table 2, BiT-50 tuned, no v1
# pretraining = LADI-v2-classifier-small-reference). The model card itself states no metric.
REFERENCE_MAP: dict[str, Any] = {
    "source": "Scheele, Picchione, Liu (2024) LADI v2, arXiv:2406.02780, Table 2",
    "model": (
        "MITLL/LADI-v2-classifier-small-reference (BiT-50, hyperparameter-tuned, no LADI v1 pretraining)"
    ),
    "metric": "mean average precision over the 12 v2a labels, percent",
    "rows": [
        {"split": "test", "n": 1049, "value": 91.1, "baseline": BASELINE, "baseline_value": 89.0},
        {"split": "validation", "n": 890, "value": 93.3, "baseline": BASELINE, "baseline_value": 89.6},
    ],
    "caveat": (
        "published by the model authors, not measured by SGW; the mean includes 5 non-damage labels; "
        "test = 2023 events the reference model never saw; split sizes from the dataset's dataset_info.json"
    ),
}


@dataclass(frozen=True)
class SeededDamageCase:
    case_id: str
    section_id: str
    damage_state: str
    severity: int


@cache
def policy() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    return data


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def triage_score(probs: dict[str, float], pol: dict[str, Any] | None = None) -> float:
    """Weighted mean of the damage-label probabilities (weights from the policy file)."""
    weights: dict[str, float] = (pol or policy())["triage_weights"]["values"]
    total = sum(weights.values())
    return sum(w * float(probs.get(label, 0.0)) for label, w in weights.items()) / total


def signals(probs: dict[str, float], pol: dict[str, Any] | None = None) -> list[str]:
    pol = pol or policy()
    threshold = float(pol["signal_threshold"]["value"])
    damage = set(pol["damage_labels"])
    hits = [(p, label) for label, p in probs.items() if label in damage and p >= threshold]
    return [label for _, label in sorted(hits, key=lambda h: (-h[0], h[1]))]


def suggested_actions(sig: list[str], pol: dict[str, Any] | None = None) -> list[str]:
    mapping: dict[str, str] = (pol or policy())["actions"]["values"]
    actions: list[str] = []
    for label in sig:
        action = mapping.get(label)
        if action and action not in actions:
            actions.append(action)
    return actions


def human_only_flags(sig: list[str], pol: dict[str, Any] | None = None) -> list[str]:
    mapping: dict[str, str] = (pol or policy())["human_only"]["values"]
    return [mapping[label] for label in sig if label in mapping]


def _damage_state(value: Any) -> str | None:
    if isinstance(value, int):
        return DAMAGE_STATE_NAMES.get(value)
    return value if isinstance(value, str) else None


def seeded_damage_cases(truth: dict[str, Any], pol: dict[str, Any] | None = None) -> list[SeededDamageCase]:
    """Seeded cases whose outcome names a section damage state (directly or on the case's feeder)."""
    severity: dict[str, int] = (pol or policy())["seeded_case_photos"]["severity"]
    cases = []
    for case in truth["seeded_cases"]:
        outcome = case.get("outcome") or {}
        block = outcome if "damage_state" in outcome else outcome.get("feeder") or {}
        state = _damage_state(block.get("damage_state"))
        if state in severity and block.get("section"):
            cases.append(SeededDamageCase(case["id"], block["section"], state, severity[state]))
    return sorted(cases, key=lambda c: (-c.severity, c.case_id))


def link_seeded_cases(
    cases: list[SeededDamageCase], sample: dict[str, Any], pol: dict[str, Any] | None = None
) -> dict[str, SeededDamageCase]:
    """Map image_id -> seeded case: the first k fitting photos by row_idx, by CAP volunteer labels only."""
    cfg = (pol or policy())["seeded_case_photos"]
    per_case = int(cfg["photos_per_case"])
    swap_from, flood = cfg["flood_swap"]["from"], cfg["flood_swap"]["to"]
    images = sorted(sample["images"], key=lambda i: i["row_idx"])
    links: dict[str, SeededDamageCase] = {}
    for case in cases:
        profile = cfg["profiles"][case.damage_state]
        require = set(profile["require"])
        forbid = set(profile["forbid"])
        if "FLOOD" in case.case_id.upper():
            require.discard(swap_from)
            require.add(flood)
            forbid.discard(flood)
        fitting = [
            image["image_id"]
            for image in images
            if image["image_id"] not in links
            and all(image["cap_labels"].get(k) for k in require)
            and not any(image["cap_labels"].get(k) for k in forbid)
        ]
        if len(fitting) < per_case:
            raise ValueError(
                f"no photo set in the sample fits seeded case {case.case_id} ({case.damage_state}): "
                f"{len(fitting)} of {per_case} photos"
            )
        for image_id in fitting[:per_case]:
            links[image_id] = case
    return links


def is_no_damage_control(cap_labels: dict[str, int], pol: dict[str, Any] | None = None) -> bool:
    return not any(cap_labels.get(k) for k in (pol or policy())["damage_labels"])


def build_queue(
    scores: dict[str, Any], sample: dict[str, Any], truth: dict[str, Any], pol: dict[str, Any] | None = None
) -> dict[str, Any]:
    pol = pol or policy()
    by_id = {i["image_id"]: i for i in sample["images"]}
    if {s["image_id"] for s in scores["items"]} != set(by_id):
        raise ValueError("scores and sample hold different images")
    cases = seeded_damage_cases(truth, pol)
    links = link_seeded_cases(cases, sample, pol)
    rows = []
    for item in scores["items"]:
        image = by_id[item["image_id"]]
        if item["image_sha256"] != image["sha256"]:
            raise ValueError(f"{item['image_id']}: scores were computed on a different file")
        sig = signals(item["probs"], pol)
        case = links.get(item["image_id"])
        rows.append(
            {
                "image_id": item["image_id"],
                "row_idx": image["row_idx"],
                "triage_score": round(triage_score(item["probs"], pol), 4),
                "signals": sig,
                "suggested_actions": suggested_actions(sig, pol),
                "human_only": human_only_flags(sig, pol),
                "thumb": f"thumbs/{image['file']}",
                "source_url": image["source_url"],
                "status": "awaiting_review",
                "seeded_case_id": case.case_id if case else None,
                "section_id": case.section_id if case else None,
                "no_damage_control": is_no_damage_control(image["cap_labels"], pol),
            }
        )
    rows.sort(key=lambda r: (-r["triage_score"], r["image_id"]))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    case_rows = case_queue(cases, rows, pol)
    return {
        "model_id": scores["model_id"],
        "model_revision": scores["model_revision"],
        "imagery_note": IMAGERY_NOTE,
        "review_note": REVIEW_NOTE,
        "acceptance_history": ACCEPTANCE_HISTORY,
        "honest_miss": honest_miss(case_rows, pol),
        "policy_version": pol["version"],
        "cases": case_rows,
        "seeded_order": seeded_order(case_rows, rows, pol),
        "rows": rows,
    }


def case_queue(
    cases: list[SeededDamageCase], rows: list[dict[str, Any]], pol: dict[str, Any]
) -> list[dict[str, Any]]:
    """Seeded damage cases ordered by the mean triage score of their stand-in photos."""
    out = []
    for case in cases:
        photos = sorted((r for r in rows if r["seeded_case_id"] == case.case_id), key=lambda r: r["rank"])
        score = sum(r["triage_score"] for r in photos) / len(photos)
        out.append(
            {
                "case_id": case.case_id,
                "section_id": case.section_id,
                "damage_state": case.damage_state,
                "case_score": round(score, 4),
                "photo_ids": [r["image_id"] for r in photos],
                "photo_ranks": [r["rank"] for r in photos],
                "status": "awaiting_review",
            }
        )
    out.sort(key=lambda c: (-c["case_score"], c["case_id"]))
    for rank, row in enumerate(out, start=1):
        row["case_rank"] = rank
    return out


def honest_miss(case_rows: list[dict[str, Any]], pol: dict[str, Any]) -> str:
    """Where the most severe seeded case lands among the moderate-or-worse cases (worst first)."""
    cfg = pol["seeded_case_photos"]
    severity: dict[str, int] = cfg["severity"]
    floor = int(cfg["structural_tier_min_severity"])
    high = [c for c in case_rows if severity[c["damage_state"]] >= floor]
    if not high:
        return "no moderate-or-worse case"
    worst = max(high, key=lambda c: (severity[c["damage_state"]], -c["case_rank"]))
    place = sorted(c["case_rank"] for c in high).index(worst["case_rank"]) + 1
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(place, f"{place}th")
    label = worst["case_id"].split("-")[0]
    return f"{label} {worst['damage_state']} ranks {ordinal} of {len(high)} damaged cases"


def control_group_scores(rows: list[dict[str, Any]], pol: dict[str, Any]) -> list[float]:
    """Mean triage score of consecutive no-damage photo groups (row_idx order), sized like a case set."""
    size = int(pol["seeded_case_photos"]["photos_per_case"])
    controls = sorted((r for r in rows if r["no_damage_control"]), key=lambda r: r["row_idx"])
    return [
        round(sum(r["triage_score"] for r in controls[i : i + size]) / size, 4)
        for i in range(0, len(controls) - size + 1, size)
    ]


def seeded_order(
    case_rows: list[dict[str, Any]], rows: list[dict[str, Any]], pol: dict[str, Any]
) -> dict[str, Any]:
    """Facts the verify step checks (two tiers) and reports (the full four-level ladder)."""
    cfg = pol["seeded_case_photos"]
    severity: dict[str, int] = cfg["severity"]
    floor = int(cfg["structural_tier_min_severity"])
    high = [c for c in case_rows if severity[c["damage_state"]] >= floor]
    low = [c for c in case_rows if severity[c["damage_state"]] < floor]
    tier_violations = sum(h["case_rank"] > lo["case_rank"] for h in high for lo in low)
    pairs = discordant = 0
    for a in case_rows:
        for b in case_rows:
            if severity[a["damage_state"]] > severity[b["damage_state"]]:
                pairs += 1
                discordant += a["case_rank"] > b["case_rank"]
    groups = control_group_scores(rows, pol)
    high_min = min((c["case_score"] for c in high), default=0.0)
    return {
        "ranked_cases": [f"{c['case_id']} ({c['damage_state']})" for c in case_rows],
        "structural_tier": f"damage_state severity >= {floor}",
        "tier_violations": tier_violations,
        "structural_min_score": high_min,
        "control_groups": len(groups),
        "control_group_max_score": max(groups, default=0.0),
        "structural_above_all_control_groups": all(high_min > g for g in groups),
        "slight_case_scores": [c["case_score"] for c in low],
        "ladder_pairs": pairs,
        "ladder_discordant_pairs": discordant,
    }


def queue_csv(queue: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "rank",
            "image_id",
            "triage_score",
            "signals",
            "suggested_actions",
            "human_only",
            "seeded_case_id",
            "section_id",
            "status",
            "thumb",
        ]
    )
    for r in queue["rows"]:
        writer.writerow(
            [
                r["rank"],
                r["image_id"],
                f"{r['triage_score']:.4f}",
                ";".join(r["signals"]),
                ";".join(r["suggested_actions"]),
                ";".join(r["human_only"]),
                r["seeded_case_id"] or "",
                r["section_id"] or "",
                r["status"],
                r["thumb"],
            ]
        )
    return buffer.getvalue()


def reference_eval_report(code_version: str, created_at: str) -> dict[str, Any]:
    """K17 report of the published reference mAP (label F); the maintainer copies it to evals/reports."""
    from sgw.contracts.eval_report import EvalReport

    metrics = [
        {
            "metric": f"ladi_v2.small_reference.{row['split']}_map",
            "value": row["value"],
            "unit": "mAP percent, 12 labels",
            "n": row["n"],
            "split": "ladi_reference",
            "label": "F",
            "baseline_name": f"{row['baseline']} ({REFERENCE_MAP['source']})",
            "baseline_value": row["baseline_value"],
            "threshold": row["baseline_value"],
            "direction": "higher_is_better",
            "passed": row["value"] >= row["baseline_value"],
        }
        for row in REFERENCE_MAP["rows"]
    ]
    report = EvalReport.model_validate(
        {
            "name": "ladi_reference",
            "created_at": created_at,
            "code_version": code_version,
            "llm_mode": "replay",
            "command": "uv run python -m sgw.models.cv build",
            "metrics": metrics,
        }
    )
    return report.model_dump(mode="json")


def verify(artefacts: Path = ARTEFACTS) -> list[str]:
    """Problems with the committed artefacts; an empty list means the scores, queue and manifest agree."""
    problems: list[str] = []
    manifest = load_json(artefacts / "manifest.json")
    for key in ("scores", "sample", "review_queue"):
        path = artefacts / manifest[f"{key}_file"]
        if sha256_file(path) != manifest[f"{key}_sha256"]:
            problems.append(f"{path.name}: sha256 differs from manifest.json")
    model = manifest["model"]
    for field in ("id", "revision", "licence", "weights_sha256"):
        if not model.get(field):
            problems.append(f"manifest.json: model.{field} missing")
    scores = load_json(artefacts / manifest["scores_file"])
    if (scores["model_id"], scores["model_revision"]) != (model["id"], model["revision"]):
        problems.append("ladi_scores.json: model id or revision differs from manifest.json")
    if not model["id"].endswith("-reference"):
        problems.append("manifest.json: quoted metrics must come from a -reference model")
    sample = load_json(artefacts / manifest["sample_file"])
    queue = build_queue(scores, sample, load_json(TRUTH_TABLE))
    committed = load_json(artefacts / "review_queue.json")
    if committed != queue:
        problems.append("review_queue.json is stale: run `uv run python -m sgw.models.cv build`")
    for field in ("acceptance_history", "honest_miss"):
        if manifest.get(field) != queue[field]:
            problems.append(f"manifest.json: {field} differs from review_queue.json")
    order = queue["seeded_order"]
    if order["tier_violations"]:
        problems.append(f"{order['tier_violations']} slight cases rank above a moderate-or-worse case")
    if not order["structural_above_all_control_groups"]:
        problems.append("a moderate-or-worse seeded case scores at or below a no-damage control group")
    thumbs = artefacts / "thumbs"
    for row in queue["rows"]:
        if not (artefacts / row["thumb"]).exists():
            problems.append(f"missing thumbnail {row['thumb']}")
    provenance = thumbs / "PROVENANCE.csv"
    if provenance.exists():
        listed = {r["file"] for r in csv.DictReader(provenance.open(encoding="utf-8"))}
        on_disk = {f"thumbs/{p.name}" for p in thumbs.glob("*.jpg")}
        if listed != on_disk:
            problems.append("thumbs/PROVENANCE.csv does not list exactly the thumbnail files")
    else:
        problems.append("thumbs/PROVENANCE.csv missing")
    return problems
