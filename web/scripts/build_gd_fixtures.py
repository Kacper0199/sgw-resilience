"""Exports the observed Helene layers and the official record that Map and After-action read on MSW (GD).

Snapshots of `GET /api/hazard/observed` at five times of the mock replay (warnings simplified further, gauges
that never reach flood stage thinned) and `GET /api/after-action/official-record` at the end of the scenario,
all from `sgw.opendata.read` over the committed `data/open/` files. Run from the repository root:
`uv run --frozen python -I web/scripts/build_gd_fixtures.py`.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import shape
from shapely.ops import unary_union

from sgw.opendata import read
from sgw.opendata.build import simplified_multipolygon

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "web/src/features/map/mock/observed.gen.json"
TIMES = (
    "2024-09-24T15:00:00Z",
    "2024-09-25T03:00:00Z",
    "2024-09-26T09:00:00Z",
    "2024-09-26T21:00:00Z",
    "2024-09-27T01:00:00Z",
)
RECORD_AT = datetime(2024, 10, 5, tzinfo=UTC)
BELOW_EVERY = 4
MOCK_SIMPLIFY = 0.02
MOCK_CLOSE = 0.01


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def merged_by_kind(warnings: list[dict]) -> list[dict]:
    """One area per warning kind (the earliest warning's id and times), simplified for a small fixture."""
    out = []
    for kind in dict.fromkeys(w["kind"] for w in warnings):
        same = [w for w in warnings if w["kind"] == kind]
        geom = unary_union([shape(w["geometry"]).buffer(MOCK_CLOSE) for w in same]).buffer(-MOCK_CLOSE)
        geom = geom.simplify(MOCK_SIMPLIFY)
        merged = simplified_multipolygon(geom)
        if merged:
            out.append({**same[0], "geometry": merged})
    return out


def main() -> None:
    ever = {g.gauge_id for g in read.gauges_at(utc("2024-10-02T23:00:00Z")) if g.category != "below"}
    snapshots = []
    for i, text in enumerate(TIMES):
        body = read.observed(utc(text)).model_dump(mode="json")
        body["gauges"] = [
            g for k, g in enumerate(body["gauges"]) if g["gauge_id"] in ever or k % BELOW_EVERY == 0
        ]
        body["warnings"] = merged_by_kind(body["warnings"])
        snapshots.append(body)
        print(i, text, len(body["gauges"]), len(body["warnings"]))
    record = read.official_record(RECORD_AT).model_dump(mode="json")
    OUT.write_text(
        json.dumps({"observed": snapshots, "record": record}, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(OUT.relative_to(ROOT), OUT.stat().st_size)


if __name__ == "__main__":
    main()
