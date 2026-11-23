"""Label sensitivities from the raw EAGLE-I extracts (never the headline labels).

- L2 hazard-conditioned window: per county, from the first time the modelled gust reaches 13 m/s minus 6 h to
  the last time plus 48 h (counties never at 13 m/s: closest approach - 6 h to + 48 h). The pre-storm level is
  L1's (median of the 72 h before the L1 window), so only the window changes. `peak_frac_l2` is cut to [0, 1].
- Gap share: a missing 15-min slot inside the L1 window is a gap when the nearest reported values before and
  after it both exceed 0.5% of MCC customers (an ongoing outage cannot read zero in between); `gap_flag` = 1
  above 20% of the window's slots.

Output: `data/open/eaglei/county_storm_labels_v3.csv`. Rebuild:
`uv run python -m sgw.models.outage.labels_v3 <raw/data/eaglei>`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, OPEN_DIR, Storm, load_track
from sgw.models.hazard.series import gust_series
from sgw.models.outage.eaglei import PRE_H, raw_file, read_mcc, storm_window

LABELS_V3_CSV = OPEN_DIR / "county_storm_labels_v3.csv"
GAP_LEVEL = 0.005
GAP_FLAG = 0.20


def _series(raw: pd.DataFrame, fips: str, grid: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    one = raw[raw["fips_code"] == fips].groupby("t")["customers_out"].max().reindex(grid)
    return one.fillna(0.0).astype(float), one.notna()


def gap_share(values: pd.Series, reported: pd.Series, in_window: np.ndarray, level: float) -> float:
    known = values.where(reported)
    before, after = known.ffill(), known.bfill()
    gap = (~reported) & (before > level) & (after > level)
    return float(gap[in_window].mean()) if in_window.any() else 0.0


def derive_storm(storm: Storm, raw_dir: Path, mcc: dict[str, int]) -> list[dict[str, object]]:
    from sgw.models.outage.dataset import county_points

    points, _ = county_points()
    start, end = storm_window(storm)
    ser = gust_series(load_track(storm.name), points)
    w_lo, w_hi = ser.windows()
    lo = min(start, datetime.fromtimestamp(float(w_lo.min()), tz=UTC))
    hi = max(end, datetime.fromtimestamp(float(w_hi.max()), tz=UTC))
    pre_start = start - timedelta(hours=PRE_H)
    from sgw.models.outage.eaglei import read_raw

    raw = read_raw(raw_dir / raw_file(storm), points.ids, min(pre_start, lo), hi)
    raw = raw.assign(customers_out=pd.to_numeric(raw["customers_out"], errors="coerce"))
    grid = pd.date_range(min(pre_start, lo), hi, freq="15min", inclusive="left", tz=UTC)
    rows = []
    for i, f in enumerate(points.ids):
        values, reported = _series(raw, f, grid)
        pre = float(values[(values.index >= pre_start) & (values.index < start)].median())
        l2 = (grid >= pd.Timestamp(w_lo[i], unit="s", tz=UTC)) & (
            grid < pd.Timestamp(w_hi[i], unit="s", tz=UTC)
        )
        l1 = (grid >= start) & (grid < end)
        excess = float((values[l2] - pre).clip(lower=0.0).max()) if l2.any() else 0.0
        customers = mcc[f]
        rows.append(
            {
                "storm": storm.name,
                "fips": f,
                "l2_start_utc": pd.Timestamp(w_lo[i], unit="s", tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "l2_end_utc": pd.Timestamp(w_hi[i], unit="s", tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "peak_frac_l2": round(min(excess / customers, 1.0), 6) if customers else 0.0,
                "gap_share": round(gap_share(values, reported, l1, GAP_LEVEL * customers), 4),
            }
        )
    return rows


def derive_labels_v3(raw_dir: Path, out: Path = LABELS_V3_CSV) -> pd.DataFrame:
    mcc = read_mcc(raw_dir / "MCC.csv")
    frame = pd.DataFrame([r for s in EXTENDED_STORMS for r in derive_storm(s, raw_dir, mcc)])
    frame["gap_flag"] = (frame["gap_share"] > GAP_FLAG).astype(int)
    frame.to_csv(out, index=False, lineterminator="\n")
    return frame


def load_labels_v3(path: Path = LABELS_V3_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"fips": str})


if __name__ == "__main__":
    import sys

    out = derive_labels_v3(Path(sys.argv[1]))
    print(out.groupby("storm")[["peak_frac_l2", "gap_share", "gap_flag"]].agg(["mean", "max"]).round(3))
