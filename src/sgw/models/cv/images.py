"""Full-size damage photos on this machine (LADI v2 test split, CC BY 4.0) and the per-label scores of the
reference model, for the photo preview. Images are not committed: `uv run sgw photos` downloads the 200
sampled files into a git-ignored folder (`SGW_CV_IMAGES_DIR`, default `var/cv/ladi_v2/images`) and checks
each sha256 against `data/artefacts/cv/sample.json`. A file is served only for an image id the sample lists,
from a path that resolves inside that folder and whose bytes match the recorded sha256; otherwise the caller
falls back to the committed 240 px thumbnail."""

from __future__ import annotations

import hashlib
import json
import os
from functools import cache
from pathlib import Path
from typing import Any

from sgw.models.cv import read

SAMPLE_PATH = read.ARTEFACTS / "sample.json"
SCORES_PATH = read.ARTEFACTS / "ladi_scores.json"
IMAGES_ENV = "SGW_CV_IMAGES_DIR"
DEFAULT_IMAGES_DIR = read.ROOT / "var" / "cv" / "ladi_v2" / "images"
IMAGE_ROUTE = "/api/damage/images/{image_id}"
DAMAGE_LABELS = (
    "buildings_affected_or_greater",
    "buildings_minor_or_greater",
    "roads_damage",
    "trees_damage",
    "debris_any",
    "flooding_structures",
    "flooding_any",
    "bridges_any",
)


def images_dir() -> Path:
    configured = os.environ.get(IMAGES_ENV)
    return Path(configured) if configured else DEFAULT_IMAGES_DIR


@cache
def _sample() -> dict[str, dict[str, Any]]:
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return {str(i["image_id"]): i for i in data["images"]}


@cache
def sample_meta() -> dict[str, str]:
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return {"dataset": str(data["dataset_id"]), "licence": str(data["licence"])}


@cache
def _scores() -> dict[str, dict[str, float]]:
    data = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    return {str(i["image_id"]): {str(k): float(v) for k, v in i["probs"].items()} for i in data["items"]}


def label_scores(image_id: str) -> list[tuple[str, float]]:
    """The damage labels' scores of one photo, highest first (presence-only labels such as `roads_any` left
    out: they say what is in the picture, not what is damaged)."""
    probs = _scores().get(image_id, {})
    found = [(label, probs[label]) for label in DAMAGE_LABELS if label in probs]
    return sorted(found, key=lambda x: (-x[1], x[0]))


@cache
def _verified(path: Path, size: int, mtime_ns: int, sha256: str) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest() == sha256


def image_path(image_id: str, folder: Path | None = None) -> Path | None:
    """The verified full-size file of a sampled image, or None: unknown id, no file, a path outside the
    folder (symlink or `..`), not a .jpg, or bytes that differ from the recorded sha256."""
    item = _sample().get(image_id)
    if item is None or not item.get("sha256"):
        return None
    base = (folder or images_dir()).resolve()
    candidate = (base / str(item["file"])).resolve()
    if not candidate.is_relative_to(base) or candidate.suffix.lower() != ".jpg" or not candidate.is_file():
        return None
    stat = candidate.stat()
    return candidate if _verified(candidate, stat.st_size, stat.st_mtime_ns, str(item["sha256"])) else None
