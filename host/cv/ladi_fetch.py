"""LADI-v2 test-split sample for the WP-36 review queue: select 200 images, fetch them, check sha256.

Images are not committed; `data/artefacts/cv/sample.json` holds row ids, CAP labels and sha256 per file.

    uv run python host/cv/ladi_fetch.py select            # rebuild sample.json from the dataset labels
    uv run python host/cv/ladi_fetch.py fetch             # download into var/cv/ladi_v2/images, verify sha256
    uv run python host/cv/ladi_fetch.py fetch --from-dir <dir with test_NNNN.jpg>   # copy a local cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "artefacts" / "cv" / "sample.json"
DEFAULT_DEST = ROOT / "var" / "cv" / "ladi_v2" / "images"

DATASET_ID = "MITLL/LADI-v2-dataset"
DATASET_REVISION = "5f2dbfe8c466d32edafd1bab847ec5252309acdb"
DATASET_LICENCE = "CC-BY-4.0"
SPLIT = "test"
ROWS_API = "https://datasets-server.huggingface.co/rows"
VIEWER = "https://huggingface.co/datasets/MITLL/LADI-v2-dataset/viewer/default/test?row={row_idx}"
SELECTION_SEED = 0
SAMPLE_SIZE = 200
PRIORITY_LABELS = (
    "roads_damage",
    "flooding_structures",
    "bridges_any",
    "flooding_any",
    "debris_any",
    "buildings_minor_or_greater",
    "buildings_affected_or_greater",
    "trees_damage",
)
CAP_PER_LABEL = {"trees_damage": 40}
DEFAULT_CAP = 30


def rows_url(offset: int, length: int) -> str:
    query = urllib.parse.urlencode(
        {"dataset": DATASET_ID, "config": "default", "split": SPLIT, "offset": offset, "length": length}
    )
    return f"{ROWS_API}?{query}"


def backoff_s(response: httpx.Response | None, attempt: int) -> float:
    """Seconds before the next try: the server's Retry-After when sent, else a growing wait."""
    retry_after = response.headers.get("retry-after", "") if response is not None else ""
    return float(retry_after) if retry_after.isdigit() else min(60.0, 5.0 * (attempt + 1))


def get_json(url: str, attempts: int = 8) -> Any:
    for attempt in range(attempts):
        try:
            response = httpx.get(url, timeout=60, follow_redirects=True)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            if attempt == attempts - 1 or error.response.status_code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(backoff_s(error.response, attempt))
        except httpx.HTTPError:
            if attempt == attempts - 1:
                raise
            time.sleep(backoff_s(None, attempt))
    raise RuntimeError("unreachable")


def all_test_labels() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        batch = get_json(rows_url(offset, 100))["rows"]
        if not batch:
            break
        for record in batch:
            labels = {k: int(v) for k, v in record["row"].items() if k != "image"}
            rows.append({"row_idx": record["row_idx"], **labels})
        offset += 100
    return rows


def select(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Label-enriched selection (seed 0): positives of the rare damage labels first, then negatives."""
    rng = random.Random(SELECTION_SEED)  # noqa: S311
    chosen: list[dict[str, Any]] = []
    taken: set[int] = set()
    for label in PRIORITY_LABELS:
        candidates = [r for r in rows if r[label] and r["row_idx"] not in taken]
        rng.shuffle(candidates)
        for row in candidates[: CAP_PER_LABEL.get(label, DEFAULT_CAP)]:
            chosen.append(row)
            taken.add(row["row_idx"])
    negatives = [r for r in rows if r["row_idx"] not in taken and not any(r[k] for k in PRIORITY_LABELS)]
    rng.shuffle(negatives)
    chosen += negatives[: max(0, SAMPLE_SIZE - len(chosen))]
    return chosen[:SAMPLE_SIZE]


def image_name(row_idx: int) -> str:
    return f"test_{row_idx:04d}.jpg"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def image_sources(row_ids: set[int], page: int = 100) -> dict[int, str]:
    """Image URLs of the wanted rows, read page by page (a few calls instead of one per image)."""
    found: dict[int, str] = {}
    for offset in sorted({(r // page) * page for r in row_ids}):
        for record in get_json(rows_url(offset, page))["rows"]:
            if record["row_idx"] in row_ids:
                found[record["row_idx"]] = record["row"]["image"]["src"]
    return found


def download(row_idx: int, src: str, dest: Path) -> None:
    """Stream into a `.part` file and rename it only when complete, so a cut download never looks done."""
    if f"/{DATASET_REVISION}/" not in src:
        print(f"warning: row {row_idx} served from another dataset revision: {src}", file=sys.stderr)
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", src, timeout=120, follow_redirects=True) as response, part.open("wb") as out:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            out.write(chunk)
    part.replace(dest)


def cmd_select(args: argparse.Namespace) -> int:
    rows = json.loads(Path(args.labels).read_text()) if args.labels else all_test_labels()
    chosen = select(rows)
    previous = json.loads(SAMPLE.read_text()) if SAMPLE.exists() else None
    known = {i["row_idx"]: i for i in previous["images"]} if previous else {}
    images = []
    for row in chosen:
        labels = {k: v for k, v in row.items() if k != "row_idx"}
        images.append(
            {
                "image_id": f"ladi-v2-test-{row['row_idx']:04d}",
                "row_idx": row["row_idx"],
                "file": image_name(row["row_idx"]),
                "sha256": known.get(row["row_idx"], {}).get("sha256"),
                "source_url": VIEWER.format(row_idx=row["row_idx"]),
                "cap_labels": labels,
            }
        )
    payload = {
        "dataset_id": DATASET_ID,
        "dataset_revision": DATASET_REVISION,
        "licence": DATASET_LICENCE,
        "split": SPLIT,
        "split_rows": len(rows),
        "selection": (
            f"label-enriched, seed {SELECTION_SEED}: up to {DEFAULT_CAP} positives each of "
            f"{', '.join(PRIORITY_LABELS[:-1])} and {CAP_PER_LABEL['trees_damage']} of trees_damage, "
            "then negatives; not a population sample"
        ),
        "fetch": "uv run python host/cv/ladi_fetch.py fetch",
        "images": images,
    }
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    SAMPLE.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    print(f"selected {len(images)} of {len(rows)} test rows -> {SAMPLE.relative_to(ROOT)}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    sample = json.loads(SAMPLE.read_text())
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    source = Path(args.from_dir) if args.from_dir else None
    bad = 0
    for item in sample["images"]:
        target = dest / item["file"]
        if target.exists() and item["sha256"] is not None and sha256_file(target) != item["sha256"]:
            target.unlink()
    missing = [i for i in sample["images"] if not (dest / i["file"]).exists()]
    sources = image_sources({i["row_idx"] for i in missing}) if missing and source is None else {}
    for item in sample["images"]:
        target = dest / item["file"]
        if not target.exists():
            if source is not None:
                shutil.copyfile(source / item["file"], target)
            elif item["row_idx"] in sources:
                download(item["row_idx"], sources[item["row_idx"]], target)
            else:
                print(f"not found in the dataset: row {item['row_idx']}", file=sys.stderr)
                bad += 1
                continue
        digest = sha256_file(target)
        if item["sha256"] is None:
            item["sha256"] = digest
        elif digest != item["sha256"]:
            print(f"sha256 mismatch: {item['file']}", file=sys.stderr)
            bad += 1
    if args.record:
        SAMPLE.write_text(json.dumps(sample, indent=1, sort_keys=True) + "\n")
    print(f"{len(sample['images']) - bad} of {len(sample['images'])} images verified in {dest}")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_select = sub.add_parser("select", help="rebuild sample.json from the test-split labels")
    p_select.add_argument("--labels", help="cached JSON list of test rows (row_idx + 12 labels)")
    p_fetch = sub.add_parser("fetch", help="download or copy the sample images and verify sha256")
    p_fetch.add_argument("--dest", default=str(DEFAULT_DEST))
    p_fetch.add_argument("--from-dir", help="local folder holding test_NNNN.jpg files")
    p_fetch.add_argument("--record", action="store_true", help="write missing sha256 values to sample.json")
    args = parser.parse_args(argv)
    return cmd_select(args) if args.cmd == "select" else cmd_fetch(args)


if __name__ == "__main__":
    raise SystemExit(main())
