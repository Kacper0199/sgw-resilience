"""Read of the precomputed what-if grid (W10, T0, `helene_grid.json`) for the API: the baseline cell and the
named scenarios the Forecast screen compares, each the grid cell for one lever change. Nothing is simulated;
the grid's own levers, notes and label are passed through."""

from __future__ import annotations

from typing import Any

from sgw.contracts.api_models import Provenance, WhatIfCell, WhatIfGrid, WhatIfScenario
from sgw.contracts.vocab import NumberLabel
from sgw.models.whatif.grid import GRID_PATH, load_grid, lookup

NAMED: tuple[tuple[str, str, dict[str, float]], ...] = (
    ("track_east", "Storm track 40 km further east", {"track_shift_km": 40.0}),
    ("wind_up", "Winds 10% stronger", {"gust_scale": 1.1}),
    ("aid_late", "Mutual-aid request 12 h later", {"mutual_aid_request_shift_h": 12.0}),
)
CELL_KEYS = (
    "customer_hours",
    "customers_affected",
    "delta_customer_hours_pct",
    "hours_peak_to_90pct",
    "peak_customers_out",
    "peak_utc",
    "levers",
)


def _cell(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: raw[k] for k in CELL_KEYS if k in raw}


def whatif() -> WhatIfGrid:
    grid = load_grid()
    root = GRID_PATH.parents[4]
    return WhatIfGrid(
        scenario=grid["scenario"],
        label=grid["label"],
        mode=grid["mode"],
        tier=grid["tier"],
        metric_notes=grid["metric_notes"],
        levers=grid["levers"],
        baseline=WhatIfCell.model_validate(_cell(lookup({}, grid))),
        scenarios=[
            WhatIfScenario.model_validate({"id": i, "title": t, **_cell(lookup(change, grid))})
            for i, t, change in NAMED
        ],
        provenance=Provenance(
            source=str(GRID_PATH.relative_to(root)),
            model_id=f"whatif-grid@{grid['cells_sha256'][:12]}",
            as_of=None,
            label=NumberLabel.S,
            detail=f"precomputed {grid['mode']} grid, seed {grid['seed']}; synthetic truth model",
        ),
    )
