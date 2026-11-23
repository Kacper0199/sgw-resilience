"""Dev / held-out split of the Ask bank, by item id only: `heldout` iff int(sha256(id)[:8], 16) % 10 < 3.

`python -m sgw.evals.ask_bank.split <source.yaml>...` validates authored items and writes each into
`evals/ask_bank/<split>/<source file name>`, so an item's file always matches its id (tested).
Developers tune on dev only; the held-out files are never read during development."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import yaml

from sgw.evals.ask_bank.schema import BANK, SPLITS, read_file

HELDOUT_BUCKETS = 3


def split_of(item_id: str) -> str:
    bucket = int(hashlib.sha256(item_id.encode()).hexdigest()[:8], 16) % 10
    return "heldout" if bucket < HELDOUT_BUCKETS else "dev"


def write(sources: list[Path], bank: Path = BANK) -> dict[str, int]:
    counts = dict.fromkeys(SPLITS, 0)
    for source in sources:
        items = read_file(source)
        header = f"# Ask bank, {source.stem}: by C2 (R33) from the platform content; split by id.\n"
        for split in SPLITS:
            mine = [i.model_dump(exclude_defaults=True) for i in items if split_of(i.id) == split]
            counts[split] += len(mine)
            out = bank / split / source.name
            out.parent.mkdir(parents=True, exist_ok=True)
            body = yaml.safe_dump({"items": mine}, allow_unicode=True, sort_keys=False, width=120)
            out.write_text(header + body, encoding="utf-8")
    return counts


if __name__ == "__main__":
    print(write([Path(p) for p in sys.argv[1:]]))
