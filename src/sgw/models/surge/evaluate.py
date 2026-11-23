"""Event-level metrics of outage-surge detection against NCEI Storm Events.

A surge matches an event of its county when detected within [begin - `MATCH_PRE_H`, end + `MATCH_POST_H`].
- recall: share of label events (wind-driven county episodes) with a matching surge;
- precision: share of surges matching a label or an explaining event (a lower bound: Storm Events misses
  storms, and outages also have non-weather causes);
- false alarms per county-month: surges matching no event / county-months monitored;
- delay: detection time minus the event begin time of the first matching surge, in hours (negative = the
  outage rise was flagged before the time NCEI lists).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

MATCH_PRE_H = 3.0
MATCH_POST_H = 12.0
FA_BUDGET_DEFAULT = 0.25
HOUR_NS = 3_600_000_000_000


def _ns(values: pd.Series) -> np.ndarray:
    return pd.DatetimeIndex(values).as_unit("ns").asi8


def match(events: pd.DataFrame, surges: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Label events with `detected` and `delay_h`; surges with `explained`."""
    pre, post = int(MATCH_PRE_H * HOUR_NS), int(MATCH_POST_H * HOUR_NS)
    by_fips = {f: np.sort(_ns(g["detected_at"])) for f, g in surges.groupby("fips")}
    labels = events[events["label"]].copy()
    delays: list[float] = []
    for fips, begin, end in zip(labels["fips"], _ns(labels["begin"]), _ns(labels["end"]), strict=True):
        times = by_fips.get(fips, np.empty(0, dtype=np.int64))
        hit = times[(times >= begin - pre) & (times <= end + post)]
        delays.append((hit[0] - begin) / HOUR_NS if len(hit) else np.nan)
    labels["delay_h"] = delays
    labels["detected"] = labels["delay_h"].notna()
    windows = {f: (_ns(g["begin"]) - pre, _ns(g["end"]) + post) for f, g in events.groupby("fips")}
    explained: list[bool] = []
    for fips, t in zip(surges["fips"], _ns(surges["detected_at"]), strict=True):
        w = windows.get(fips)
        explained.append(bool(w is not None and ((w[0] <= t) & (t <= w[1])).any()))
    out = surges.copy()
    out["explained"] = explained
    return labels.reset_index(drop=True), out.reset_index(drop=True)


def summarise(events: pd.DataFrame, surges: pd.DataFrame, county_months: float) -> dict[str, Any]:
    n_events, n_surges = len(events), len(surges)
    false = int((~surges["explained"]).sum()) if n_surges else 0
    delays = events.loc[events["detected"], "delay_h"]
    return {
        "events": n_events,
        "detected": int(events["detected"].sum()),
        "recall": float(events["detected"].mean()) if n_events else 0.0,
        "surges": n_surges,
        "precision": float(surges["explained"].mean()) if n_surges else 0.0,
        "false_alarms": false,
        "county_months": round(county_months, 1),
        "false_alarms_per_county_month": false / county_months,
        "delay_h_median": float(delays.median()) if len(delays) else None,
        "delay_h_p25": float(delays.quantile(0.25)) if len(delays) else None,
        "delay_h_p75": float(delays.quantile(0.75)) if len(delays) else None,
        "share_flagged_before_begin": float((delays < 0).mean()) if len(delays) else None,
        "by_tier": {
            tier: {"events": len(g), "recall": float(g["detected"].mean())}
            for tier, g in events.groupby("tier")
        },
    }


def choose(rows: Sequence[dict[str, Any]], budget: float) -> dict[str, Any]:
    """Highest recall within the false-alarm budget; ties go to fewer false alarms, then shorter delay."""
    ok = [r for r in rows if r["false_alarms_per_county_month"] <= budget]
    if not ok:
        raise ValueError(f"no setting within {budget} false alarms per county-month")
    return max(
        ok,
        key=lambda r: (
            round(r["recall"], 6),
            -r["false_alarms_per_county_month"],
            -(r["delay_h_median"] if r["delay_h_median"] is not None else np.inf),
        ),
    )


def paired_bootstrap(
    a: np.ndarray, b: np.ndarray, days: pd.Series, reps: int = 2000, seed: int = 20261121
) -> tuple[float, float, float]:
    """Recall difference a - b on the same events with a 95% interval, resampling whole event days."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    codes, uniq = pd.factorize(pd.Series(days).dt.floor("D"))
    k = len(uniq)
    sum_a = np.bincount(codes, weights=a, minlength=k)
    sum_b = np.bincount(codes, weights=b, minlength=k)
    count = np.bincount(codes, minlength=k).astype(float)
    gen = np.random.default_rng(seed)
    draws = gen.integers(0, k, size=(reps, k))
    w = np.apply_along_axis(np.bincount, 1, draws, minlength=k)
    diffs = (w @ sum_a - w @ sum_b) / (w @ count)
    point = float(a.mean() - b.mean())
    low, high = np.quantile(diffs, [0.025, 0.975])
    return point, float(min(low, point)), float(max(high, point))
