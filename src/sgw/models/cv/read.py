"""Read of the CV damage-triage review queue (WP-36 `data/artefacts/cv/review_queue.json`) for the API, and
safe thumbnail lookup: a thumbnail is served only for an image id the queue lists, from a path that resolves
inside the thumbnail folder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.contracts.api_models import DamageQueue, Provenance
from sgw.contracts.vocab import NumberLabel

ROOT = Path(__file__).resolve().parents[4]
ARTEFACTS = ROOT / "data" / "artefacts" / "cv"
QUEUE_PATH = ARTEFACTS / "review_queue.json"
MANIFEST_PATH = ARTEFACTS / "manifest.json"
THUMBS_DIR = ARTEFACTS / "thumbs"
POLICY_PATH = Path(__file__).with_name("queue_policy.yaml")
THUMB_ROUTE = "/api/damage/thumbs/{image_id}"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
LABEL = (
    "reference model scores on benchmark imagery (LADI-v2 test split, CC-BY-4.0); seeded damage cases are "
    "synthetic; SGW queue policy assumed"
)


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@cache
def _tiering() -> tuple[dict[str, int], int]:
    cfg = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))["seeded_case_photos"]
    return {str(k): int(v) for k, v in cfg["severity"].items()}, int(cfg["structural_tier_min_severity"])


def tier_of(damage_state: str) -> str:
    severity, floor = _tiering()
    return "structural" if severity[damage_state] >= floor else "slight"


def queue_row(image_id: str, queue_path: Path = QUEUE_PATH) -> dict[str, Any] | None:
    """One queued photo's row, or None for an id the queue does not list."""
    return next((r for r in _load(queue_path)["rows"] if r.get("image_id") == image_id), None)


def queue_model(queue_path: Path = QUEUE_PATH) -> str:
    q = _load(queue_path)
    return f"{q['model_id']}@{q['model_revision']}"


def thumb_path(image_id: str, queue_path: Path = QUEUE_PATH, thumbs: Path = THUMBS_DIR) -> Path | None:
    """The thumbnail file of a queued image, or None: unknown id, no thumbnail, or a path outside `thumbs`."""
    rows = _load(queue_path)["rows"]
    rel = next((r.get("thumb") for r in rows if r.get("image_id") == image_id), None)
    if not rel:
        return None
    base = thumbs.resolve()
    candidate = (thumbs.parent / str(rel)).resolve()
    if not candidate.is_relative_to(base) or candidate.suffix.lower() != ".jpg" or not candidate.is_file():
        return None
    return candidate


def damage_queue(limit: int = DEFAULT_LIMIT, queue_path: Path = QUEUE_PATH) -> DamageQueue:
    """The top `limit` photos by queue rank, plus every photo of a seeded case; cases carry their tier."""
    q = _load(queue_path)
    cases = [{**c, "tier": tier_of(c["damage_state"])} for c in q["cases"]]
    case_tier = {pid: c["tier"] for c in cases for pid in c["photo_ids"]}
    rows = sorted(q["rows"], key=lambda r: r["rank"])
    keep = [r for r in rows if r["rank"] <= limit or r["image_id"] in case_tier]
    manifest = _load(MANIFEST_PATH) if MANIFEST_PATH.is_file() else {}
    created = manifest.get("created_at")
    order = q["seeded_order"]
    return DamageQueue.model_validate(
        {
            "cases": cases,
            "rows": [
                {
                    **{k: r[k] for k in r if k not in ("thumb", "row_idx")},
                    "tier": case_tier.get(r["image_id"]),
                    "thumb_url": THUMB_ROUTE.format(image_id=r["image_id"]) if r.get("thumb") else None,
                }
                for r in keep
            ],
            "total_photos": len(rows),
            **{
                k: q[k]
                for k in (
                    "honest_miss",
                    "imagery_note",
                    "review_note",
                    "model_id",
                    "model_revision",
                    "policy_version",
                )
            },
            "seeded_order": {k: order[k] for k in order if k not in ("ranked_cases", "slight_case_scores")},
            "provenance": Provenance(
                source=str(queue_path.relative_to(ROOT))
                if queue_path.is_relative_to(ROOT)
                else queue_path.name,
                model_id=f"{q['model_id']}@{q['model_revision']}",
                rule_id=f"cv-queue-policy@{q['policy_version']}",
                as_of=datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(UTC)
                if created
                else None,
                label=NumberLabel.C,
                detail=LABEL,
            ),
        }
    )
