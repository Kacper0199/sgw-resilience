"""Write `src/features/map/mock/county-outages.gen.json`: customers out per county in the replayed outage feed
at the observed-layer snapshot times and the post-landfall demo moments, for the mock API.

Run: `uv run python -I web/scripts/build_county_outage_fixtures.py`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sgw.models.outage.read import county_outages_now

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "src" / "features" / "map" / "mock" / "county-outages.gen.json"
TIMES = ("2024-09-26T21:00:00Z", "2024-09-27T01:00:00Z", "2024-09-27T12:00:00Z", "2024-09-30T12:00:00Z")


def main() -> None:
    reports = [county_outages_now(datetime.fromisoformat(t)).model_dump(mode="json") for t in TIMES]
    body = json.dumps({"reports": reports}, indent=1, sort_keys=True) + "\n"
    OUT.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(reports)} reports)")


if __name__ == "__main__":
    main()
