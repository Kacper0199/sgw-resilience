"""Write `src/features/map/mock/surges.gen.json`: the outage surge reports of the EAGLE-I detector at the
observed-layer snapshot times, active surges only, for the mock API.

Run: `uv run python -I web/scripts/build_surge_fixtures.py`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sgw.models.surge.read import SurgeUnavailable, list_outage_surges

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "src" / "features" / "map" / "mock" / "surges.gen.json"
TIMES = ("2024-09-25T03:00:00Z", "2024-09-26T09:00:00Z", "2024-09-26T21:00:00Z", "2024-09-27T01:00:00Z")


def main() -> None:
    reports = []
    for t in TIMES:
        try:
            report = list_outage_surges(datetime.fromisoformat(t), scenario="helene", active_only=True)
        except SurgeUnavailable:
            continue
        reports.append(report.model_dump(mode="json"))
    body = json.dumps({"reports": reports}, indent=1, sort_keys=True) + "\n"
    OUT.write_text(body, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(reports)} reports)")


if __name__ == "__main__":
    main()
