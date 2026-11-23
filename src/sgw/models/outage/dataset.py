"""Training frame: EAGLE-I targets joined with A1 hazard features per county and storm."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from sgw.generator.config import load_counties
from sgw.models.hazard.field import EXTRA_FEATURES, Points, point_features
from sgw.models.hazard.hurdat2 import EXTENDED_STORMS, STORMS, load_track
from sgw.models.outage.eaglei import load_extended_targets, load_targets


def county_points() -> tuple[Points, pd.DataFrame]:
    counties = load_counties()
    points = Points(
        ids=tuple(c.fips for c in counties),
        lat=np.array([c.lat for c in counties]),
        lon=np.array([c.lon for c in counties]),
    )
    meta = pd.DataFrame(
        {
            "fips": [c.fips for c in counties],
            "name": [c.name for c in counties],
            "st": [c.st for c in counties],
            "customers_footprint": [c.customers for c in counties],
        }
    )
    return points, meta


def with_exposure(features: pd.DataFrame, customers: pd.Series) -> pd.DataFrame:
    out = features.copy()
    out["log_customers"] = np.log(np.maximum(customers.to_numpy(dtype=float), 1.0))
    return out


def storm_features(storm: str) -> pd.DataFrame:
    points, _ = county_points()
    feats = point_features(load_track(storm), points).rename(columns={"point_id": "fips"})
    feats.insert(0, "storm", storm)
    return feats


def training_frame(extended: bool = False) -> pd.DataFrame:
    targets = load_extended_targets() if extended else load_targets()
    _, meta = county_points()
    frames = [storm_features(s.name) for s in (EXTENDED_STORMS if extended else STORMS)]
    feats = pd.concat(frames, ignore_index=True)
    if not extended:
        feats = feats.drop(columns=list(EXTRA_FEATURES))
    frame = targets.merge(feats, on=["storm", "fips"], how="inner", validate="one_to_one").merge(
        meta, on="fips", how="left", validate="many_to_one"
    )
    if len(frame) != len(targets):
        raise ValueError("feature join dropped rows")
    return with_exposure(frame, frame["customers_mcc"]).sort_values(["storm", "fips"]).reset_index(drop=True)


def extended_frame(rain: bool = False) -> pd.DataFrame:
    """Every storm of `EXTENDED_STORMS`; the four WP-11 storms' rows equal `training_frame()`'s.

    `rain=True` joins the observed-rain diagnostic features (never used on the serving path)."""
    frame = training_frame(extended=True)
    if not rain:
        return frame
    from sgw.models.outage.rain import load_rain

    out = frame.merge(load_rain(), on=["storm", "fips"], how="left", validate="one_to_one")
    if out[["rain_window_mm", "rain_antecedent_14d_mm"]].isna().any().any():
        raise ValueError("rain table does not cover every county and storm")
    return out


def frame_sha256(frame: pd.DataFrame) -> str:
    return hashlib.sha256(frame.to_csv(index=False, lineterminator="\n").encode()).hexdigest()
