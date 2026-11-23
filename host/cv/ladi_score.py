"""Score the LADI-v2 sample with MITLL/LADI-v2-classifier-small-reference on MPS and write the manifest.

Run under the heavy lock (make cv-score). Needs the host group plus transformers (root change pending):
    uv run --group host --with transformers==5.23.0 python host/cv/ladi_score.py
Writes data/artefacts/cv/{ladi_scores.json, manifest.json, thumbs/*.jpg, thumbs/PROVENANCE.csv}.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import torch
import transformers
from huggingface_hub import hf_hub_download
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForImageClassification

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "artefacts" / "cv"
IMAGES = ROOT / "var" / "cv" / "ladi_v2" / "images"

MODEL_ID = "MITLL/LADI-v2-classifier-small-reference"
MODEL_REVISION = "6ba5a0300601284bc6b69dddb46c8991a8ac196c"
MODEL_LICENCE = "MIT"
BASE_MODEL = {"id": "google/bit-50", "licence": "Apache-2.0"}
THUMB_MAX_PX = 240
THUMB_QUALITY = 70
DECIMALS = 4
COMMAND = "make cv-score"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def pick_device(requested: str) -> str:
    if requested != "auto":
        return requested
    return "mps" if torch.backends.mps.is_available() else "cpu"


def sync(device: str) -> None:
    if device == "mps":
        torch.mps.synchronize()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def write_thumbnail(image: Image.Image, target: Path) -> None:
    thumb = image.copy()
    thumb.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX))
    thumb.save(target, "JPEG", quality=THUMB_QUALITY, optimize=True, progressive=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", default=str(IMAGES))
    parser.add_argument("--device", default="auto", choices=["auto", "mps", "cpu"])
    parser.add_argument("--no-thumbs", action="store_true")
    args = parser.parse_args(argv)

    sample = json.loads((OUT / "sample.json").read_text())
    images_dir = Path(args.images)
    device = pick_device(args.device)
    torch.manual_seed(0)

    processor = AutoImageProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model = AutoModelForImageClassification.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model = model.to(device).eval()
    weights = Path(hf_hub_download(MODEL_ID, "model.safetensors", revision=MODEL_REVISION))
    id2label = {int(k): v for k, v in model.config.id2label.items()}
    params = sum(p.numel() for p in model.parameters())

    thumbs = OUT / "thumbs"
    if not args.no_thumbs:
        thumbs.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    timings: list[float] = []
    provenance: list[list[str]] = []
    started = time.perf_counter()
    with torch.inference_mode():
        for position, entry in enumerate(sample["images"]):
            path = images_dir / entry["file"]
            digest = sha256_file(path)
            if digest != entry["sha256"]:
                print(f"sha256 mismatch: {entry['file']}; run host/cv/ladi_fetch.py fetch", file=sys.stderr)
                return 1
            image = Image.open(path).convert("RGB")
            inputs = processor(image, return_tensors="pt").to(device)
            if position == 0:
                model(**inputs)
                sync(device)
            tick = time.perf_counter()
            probs = torch.sigmoid(model(**inputs).logits)[0].float().cpu().tolist()
            sync(device)
            timings.append(time.perf_counter() - tick)
            items.append(
                {
                    "image_id": entry["image_id"],
                    "image_sha256": digest,
                    "probs": {id2label[j]: round(p, DECIMALS) for j, p in enumerate(probs)},
                }
            )
            if not args.no_thumbs:
                thumb_name = entry["file"]
                write_thumbnail(image, thumbs / thumb_name)
                provenance.append(
                    [
                        f"thumbs/{thumb_name}",
                        entry["image_id"],
                        entry["source_url"],
                        digest,
                        f"{sample['dataset_id']}@{sample['dataset_revision']}",
                        "CC-BY-4.0",
                        "Civil Air Patrol imagery via MIT Lincoln Laboratory LADI v2",
                        f"resized to {THUMB_MAX_PX} px, JPEG quality {THUMB_QUALITY}",
                    ]
                )
    total = time.perf_counter() - started

    scores = {
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "labels": [id2label[j] for j in sorted(id2label)],
        "items": items,
    }
    scores_path = OUT / "ladi_scores.json"
    scores_path.write_text(json.dumps(scores, indent=1, sort_keys=True) + "\n")

    thumb_files = sorted(thumbs.glob("*.jpg")) if thumbs.exists() else []
    if provenance:
        with (thumbs / "PROVENANCE.csv").open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(
                ["file", "image_id", "source_url", "source_sha256", "dataset", "licence", "credit", "changes"]
            )
            writer.writerows(provenance)

    manifest = {
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "command": COMMAND,
        "scores_file": "ladi_scores.json",
        "scores_sha256": sha256_file(scores_path),
        "sample_file": "sample.json",
        "sample_sha256": sha256_file(OUT / "sample.json"),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "licence": MODEL_LICENCE,
            "weights_file": "model.safetensors",
            "weights_sha256": sha256_file(weights),
            "params": params,
            "base_model": BASE_MODEL,
            "card": f"https://huggingface.co/{MODEL_ID}",
            "role": "reference model: trained on the 2015-2022 train split only, never saw 2023 test events",
        },
        "dataset": {
            "id": sample["dataset_id"],
            "revision": sample["dataset_revision"],
            "licence": "CC-BY-4.0",
            "split": sample["split"],
            "n_scored": len(items),
            "selection": sample["selection"],
            "credit": "Civil Air Patrol imagery; labels by CAP volunteers; dataset by MIT Lincoln Laboratory",
        },
        "runtime": {
            "device": device,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "python": platform.python_version(),
            "machine": f"{platform.system()} {platform.machine()}",
            "input": "1800x1200 JPEG through the model's AutoImageProcessor, batch size 1",
            "warm_s_per_image_p50": round(statistics.median(timings), 4),
            "warm_s_per_image_p95": round(percentile(timings, 0.95), 4),
            "total_s_incl_decode_and_thumbs": round(total, 1),
        },
        "thumbnails": {
            "dir": "thumbs",
            "count": len(thumb_files),
            "total_bytes": sum(f.stat().st_size for f in thumb_files),
            "max_px": THUMB_MAX_PX,
            "provenance": "thumbs/PROVENANCE.csv",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(
        f"scored {len(items)} on {device}: p50 {manifest['runtime']['warm_s_per_image_p50']} s/img, "
        f"total {manifest['runtime']['total_s_incl_decode_and_thumbs']} s, thumbs {manifest['thumbnails']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
