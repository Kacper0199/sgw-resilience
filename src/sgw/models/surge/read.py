"""Outage surges in force at a scenario time, for the copilot tool `list_outage_surges` and the API.

The detector (`params.json`, fitted on 2016-2021 only) runs on the committed EAGLE-I county series of the
scenario cut at `as_of`: a 15-min slot counts as known once its collection run has ended (slot start + 15 min
<= `as_of`). Nothing after `as_of` is read, so the answer never depends on later data (tested by comparing a
cut series with the full one). Pure Python, no database and no LLM.

Served surges began inside the scenario window: one detected in the replay whose onset lies before the
window started belongs to the baseline, not to the storm, so no reader names a day before the replay. The
evaluation counts every surge detected in the window (`onset_in_window=False`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sgw.contracts.api_models import OutageSurge, SurgeReport
from sgw.models.surge.confidence import band, predict
from sgw.models.surge.detect import Surge, detect
from sgw.models.surge.fit import ARTEFACT_DIR, MODEL_VERSION, SOURCE, concurrency, params_from
from sgw.models.surge.series import read_series

SLOT = timedelta(minutes=15)
WARMUP = timedelta(hours=72)
SCENARIOS = {"helene": ("helene_series.csv.gz", datetime.fromisoformat("2024-09-23T12:00:00+00:00"))}
LABEL = "C"


class SurgeUnavailable(LookupError):
    """No series for the scenario, or `as_of` before the detector has a baseline."""


@dataclass(frozen=True)
class _Scenario:
    times: pd.DatetimeIndex
    x: np.ndarray
    fips: list[str]
    mcc: np.ndarray
    names: dict[str, tuple[str, str]]
    params: Any
    coefs: dict[str, Any]
    window_start: datetime


@cache
def scenario_data(name: str, directory: Path = ARTEFACT_DIR) -> _Scenario:
    import json

    if name not in SCENARIOS:
        raise SurgeUnavailable(f"no outage series for scenario {name!r}")
    file, start = SCENARIOS[name]
    meta = json.loads((directory / "params.json").read_text(encoding="utf-8"))
    times, x, fips = read_series(directory / file)
    counties = {c["fips"]: c for c in meta["counties"]}
    return _Scenario(
        times=times,
        x=x,
        fips=fips,
        mcc=np.array([float(counties[f]["mcc"]) for f in fips]),
        names={f: (counties[f]["name"], counties[f]["st"]) for f in fips},
        params=params_from(meta["params"]),
        coefs=meta["confidence"],
        window_start=start,
    )


@lru_cache(maxsize=512)
def _surges_at(name: str, cut: int, directory: Path = ARTEFACT_DIR) -> tuple[Surge, ...]:
    sc = scenario_data(name, directory)
    return tuple(detect(sc.x[:cut], sc.mcc, sc.times[:cut], sc.params))


def surge_id(fips: str, detected_at: pd.Timestamp) -> str:
    return f"SRG-{fips}-{detected_at.strftime('%y%m%dT%H%M')}"


def list_outage_surges(
    as_of: datetime,
    *,
    fips: Sequence[str] | None = None,
    scenario: str = "helene",
    active_only: bool = False,
    limit: int = 200,
    directory: Path = ARTEFACT_DIR,
    onset_in_window: bool = True,
) -> SurgeReport:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    sc = scenario_data(scenario, directory)
    at = pd.Timestamp(as_of).tz_convert("UTC")
    if at < sc.times[0] + WARMUP:
        raise SurgeUnavailable(f"{scenario}: no baseline before {(sc.times[0] + WARMUP).isoformat()}")
    cut = int(np.searchsorted(sc.times.as_unit("ns").asi8, (at - SLOT).as_unit("ns").value, side="right"))
    in_window = [
        s
        for s in _surges_at(scenario, cut, directory)
        if s.detected_at >= sc.window_start and (not onset_in_window or s.onset_at >= sc.window_start)
    ]
    detected = pd.Series([s.detected_at for s in in_window], dtype="datetime64[ns, UTC]")
    owners = pd.Series([sc.fips[s.county] for s in in_window], dtype=object)
    others = concurrency(owners, detected, as_of=at) if in_window else np.zeros(0, dtype=np.int64)
    excess = np.array([s.excess_share_detect for s in in_window])
    conf = predict(sc.coefs, excess, others) if in_window else np.zeros(0)
    wanted = set(fips) if fips is not None else None
    rows: list[OutageSurge] = []
    for s, p in zip(in_window, conf, strict=True):
        f = sc.fips[s.county]
        if (wanted is not None and f not in wanted) or (active_only and s.status != "active"):
            continue
        name, st = sc.names[f]
        rows.append(
            OutageSurge(
                surge_id=surge_id(f, s.detected_at),
                fips=f,
                county=name,
                state=st,
                onset_at=s.onset_at.to_pydatetime(),
                detected_at=s.detected_at.to_pydatetime(),
                status=s.status,
                customers_out=int(round(s.customers_out_last)),
                peak_customers_out=int(round(s.peak_customers_out)),
                baseline_customers_out=int(round(s.baseline_customers_out)),
                share_out=round(s.share_out, 4),
                confidence=round(float(p), 3),
                confidence_band=band(float(p), sc.coefs),  # type: ignore[arg-type]
                dq_flags=list(s.dq_flags),
            )
        )
    scope = wanted if wanted is not None else set(sc.fips)
    active = {r.fips for r in rows if r.status == "active"}
    return SurgeReport(
        as_of=at.to_pydatetime(),
        scenario=scenario,
        data_through=sc.times[cut - 1].to_pydatetime(),
        counties_monitored=len(scope & set(sc.fips)),
        counties_surging=len(active),
        surges_total=len(rows),
        first_detected_at=rows[0].detected_at if rows else None,
        model_version=MODEL_VERSION,
        source=SOURCE,
        label=LABEL,
        truncated=len(rows) > limit,
        surges=rows[:limit],
    )
