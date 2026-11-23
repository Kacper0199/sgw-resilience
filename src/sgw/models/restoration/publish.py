"""ETR estimates as published records: global and per operating area, P10/P25/P50/P75/P90 of the time to
90 percent of the peak customers out restored.

K2 has no ETR event type (contracts v1.1); the estimates are stored as K1 `forecast` rows (target
`etr_90pct_restored`, quantiles as UTC times), one `snapshot` (kind `etr`) holding the whole publication and
the serving `model_version` row. The
estimate the EOC approves (D4, T3) is the global one; regional estimates are its breakdown.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from sgw.generator.config import FIXTURES_DIR
from sgw.models.restoration import artefact
from sgw.models.restoration.conformal import Calibrator
from sgw.models.restoration.curves import censored_median, county_times, hours_to_share
from sgw.models.restoration.etr import (
    GLOBAL,
    MODEL_NAME,
    MODEL_VERSION,
    EtrModel,
    forecast,
    issue_time,
    observe,
)
from sgw.models.restoration.params import Params, default_params
from sgw.models.restoration.process import ProcessRun, simulate
from sgw.models.restoration.world import family_a_world, story_seed

FORECAST_TARGET = "etr_90pct_restored"
TARGET_TEXT = "90 percent of the peak customers out restored"
LABEL = (
    "S (synthetic family-A replay of Helene; model calibrated on family-A storms, see evals/reports/etr.json)"
)


class EtrEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    estimate_id: str
    scope: Literal["global", "region"]
    region_id: str
    as_of_utc: datetime
    target: str
    peak_customers_out: int
    customers_out_now: int
    p10_utc: datetime
    p25_utc: datetime
    p50_utc: datetime
    p75_utc: datetime
    p90_utc: datetime
    hours_from_as_of: dict[str, float]
    model_version: str
    calibrated: bool
    label: str
    replay_overlay_allowed: bool
    basis: str


def _utc(t: float) -> datetime:
    return datetime.fromtimestamp(round(t), tz=UTC)


def estimate_id(scenario: str, region_id: str, as_of: float) -> str:
    stamp = _utc(as_of).strftime("%Y%m%dT%H%MZ")
    return f"ETR-{scenario.upper()}-{region_id}-{stamp}"


def _estimate(
    scenario: str,
    scope: Literal["global", "region"],
    region_id: str,
    as_of: float,
    q_h: np.ndarray,
    peak: float,
    now: float,
    calibrated: bool,
    overlay: bool,
) -> EtrEstimate:
    names = ("p10", "p25", "p50", "p75", "p90")
    hours = {n: round(float(v), 1) for n, v in zip(names, q_h, strict=True)}
    times = {f"{n}_utc": _utc(as_of + hours[n] * 3600.0) for n in names}
    return EtrEstimate(
        estimate_id=estimate_id(scenario, region_id, as_of),
        scope=scope,
        region_id=region_id,
        as_of_utc=_utc(as_of),
        target=TARGET_TEXT,
        peak_customers_out=int(round(peak)),
        customers_out_now=int(round(now)),
        hours_from_as_of=hours,
        model_version=f"{MODEL_NAME}@{MODEL_VERSION}",
        calibrated=calibrated,
        label=LABEL,
        replay_overlay_allowed=overlay,
        basis=BASIS,
        **times,
    )


REPLAY_COUNTY_CSV = FIXTURES_DIR / "helene" / "county_hourly.csv"
REPLAY_TOLERANCE = 0.10
BASIS = (
    "WP-17 restoration process (secondary jobs, crew shifts) calibrated to EAGLE-I Helene county medians; "
    "the replay fixtures restore with the WP-06 generator process"
)


def replay_county_t90_median(path: Path = REPLAY_COUNTY_CSV) -> float:
    """County t90 median (hours from county peak to 90 percent restored) of the replayed outage curve."""
    rows: dict[str, list[tuple[str, float]]] = {}
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows.setdefault(r["fips"], []).append((r["hour_utc"], float(r["customers_out"])))
    t90 = []
    for vals in rows.values():
        vals.sort()
        curve = np.array([v for _, v in vals])
        grid = np.arange(len(curve)) * 3600.0
        t90.append(hours_to_share(curve, grid, 0.9)[2])
    return censored_median(t90)


@cache
def replay_overlay_allowed() -> bool:
    """Guard: the ETR may be drawn next to the replayed outage curve only when both come from the same
    restoration process (county t90 medians within 10 percent). False until WP-06 adopts process.simulate."""
    prm = default_params()
    story = county_times(story_run(prm), prm.f("process", "horizon_days"), prm.f("process", "step_s"))
    model = censored_median([v["t90_h"] for v in story.values()])
    return abs(replay_county_t90_median() / model - 1.0) <= REPLAY_TOLERANCE


def story_run(prm: Params | None = None, scenario: str = "helene") -> ProcessRun:
    """The story of record: the scenario's own seed, central storm effects."""
    prm = prm or default_params()
    return simulate(family_a_world(story_seed(scenario), scenario), prm)


def estimates(
    run: ProcessRun,
    hours_after_peak: float,
    model: EtrModel,
    calibrators: dict[tuple[str, float], Calibrator] | None,
    prm: Params | None = None,
    members: int | None = None,
) -> list[EtrEstimate]:
    prm = prm or default_params()
    w = run.world
    as_of = issue_time(run, prm, hours_after_peak)
    obs = observe(run, as_of, prm, w.seed)
    fc = forecast(model, obs, prm, members=members, seed=w.seed)
    reg_q, glob_q = fc.quantiles()
    overlay = replay_overlay_allowed()
    if calibrators:
        glob_q = artefact.calibrator_for(calibrators, "global", hours_after_peak).apply(glob_q)[0]
        reg_q = artefact.calibrator_for(calibrators, "regional", hours_after_peak).apply(reg_q)
    out = [
        _estimate(
            w.scenario,
            "global",
            GLOBAL,
            as_of,
            glob_q,
            obs.peak_global,
            float(obs.out_now_region.sum()),
            bool(calibrators),
            overlay,
        )
    ]
    for k in np.flatnonzero(fc.eligible):
        out.append(
            _estimate(
                w.scenario,
                "region",
                w.region_ids[k],
                as_of,
                reg_q[k],
                float(obs.peak_region[k]),
                float(obs.out_now_region[k]),
                bool(calibrators),
                overlay,
            )
        )
    return out


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write(conn: psycopg.Connection, items: list[EtrEstimate], data_hash: str) -> int:
    """One transaction: model_version, snapshot (kind etr), one forecast row per estimate. A republished
    estimate for the same issue time replaces the stored one; returns the rows inserted or changed."""
    if not items:
        return 0
    as_of = items[0].as_of_utc
    output = [e.model_dump(mode="json") for e in items]
    snap_id = f"ETR-SNAP-{items[0].estimate_id.split('-')[1]}-{as_of.strftime('%Y%m%dT%H%MZ')}"
    model_id = f"{MODEL_NAME}@{MODEL_VERSION}"
    with conn.transaction():
        conn.execute(
            "INSERT INTO model_version (model_id, name, version, data_hash, eval_report)"
            " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (model_id, MODEL_NAME, MODEL_VERSION, data_hash, "evals/reports/etr.json"),
        )
        conn.execute(
            "INSERT INTO snapshot (snapshot_id, kind, as_of, engine_version, hash, output)"
            " VALUES (%s, 'etr', %s, %s, %s, %s) ON CONFLICT (snapshot_id) DO UPDATE SET"
            " engine_version = EXCLUDED.engine_version, hash = EXCLUDED.hash, output = EXCLUDED.output",
            (snap_id, as_of, model_id, _hash(output), Jsonb(output)),
        )
        n = 0
        for e in items:
            cur = conn.execute(
                "INSERT INTO forecast (forecast_id, model_version, target, entity_id, region_id, domain,"
                " issued_at, known_at, valid_at, quantiles) VALUES (%s, %s, %s, %s, NULL, 'electric',"
                " %s, %s, %s, %s) ON CONFLICT (forecast_id) DO UPDATE SET"
                " model_version = EXCLUDED.model_version, valid_at = EXCLUDED.valid_at,"
                " quantiles = EXCLUDED.quantiles"
                " WHERE forecast.quantiles IS DISTINCT FROM EXCLUDED.quantiles",
                (
                    e.estimate_id,
                    model_id,
                    FORECAST_TARGET,
                    e.region_id,
                    e.as_of_utc,
                    e.as_of_utc,
                    e.p50_utc,
                    Jsonb(
                        {
                            "p10": e.p10_utc.isoformat(),
                            "p25": e.p25_utc.isoformat(),
                            "p50": e.p50_utc.isoformat(),
                            "p75": e.p75_utc.isoformat(),
                            "p90": e.p90_utc.isoformat(),
                            "scope": e.scope,
                            "peak_customers_out": e.peak_customers_out,
                            "replay_overlay_allowed": e.replay_overlay_allowed,
                        }
                    ),
                ),
            )
            n += cur.rowcount
    return n
