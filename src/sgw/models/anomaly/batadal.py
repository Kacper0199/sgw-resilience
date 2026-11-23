"""External check of the A7/A8 detector family on the public BATADAL benchmark (G3).

BATADAL (Taormina et al. 2018, J. Water Resour. Plann. Manage. 144(8)), C-Town hourly SCADA: dataset03 is a
year without attacks, dataset04 has attacks labelled `ATT_FLAG` 1 (five labelled windows; the organisers list
two more that are not labelled, so hours marked -999 include attack hours and TNR is a lower bound). The data
are research-use only and are not committed; only the derived metrics are.

The A7/A8 detectors run on the zone twin's station streams, which BATADAL does not have. What is checked is
the detector family with its own settings (`detector.yaml`, unchanged): a physical-consistency residual (here
the PCA reconstruction residual of the continuous sensors, fitted on dataset03 and standardised by its
dataset03 spread) fed to the same two-sided CUSUM (`cusum.k_sigma`, `cusum.h_sigma`), plus the A8 frozen and
replay signatures. Then the same residual CUSUM with only `h` recalibrated on dataset03 (the smallest h with
at most 1% alarm hours in the attack-free year; no labels used). Baselines: static SCADA limits (outside the
dataset03 range of any sensor) and a per-reading z-score >= 4 against dataset03. Scores: hour-level TPR and
TNR, attacks detected, time to detection, and the BATADAL score S = (S_TTD + S_CLF) / 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sgw.models.anomaly.detect import cusum_episodes, frozen_runs, replay_hits, settings

DATASET_TRAIN = "BATADAL_dataset03.csv"
DATASET_TEST = "BATADAL_dataset04.csv"
VAR_SHARE = 0.95
Z_BASELINE = 4.0
TRAIN_ALARM_TARGET = 0.01
HOUR_S = 3600.0


def load(path: Path) -> tuple[pd.DatetimeIndex, pd.DataFrame, np.ndarray]:
    frame = pd.read_csv(path, skipinitialspace=True)
    frame.columns = [c.strip() for c in frame.columns]
    times = pd.DatetimeIndex(pd.to_datetime(frame.pop("DATETIME"), format="%d/%m/%y %H"))
    labels = (frame.pop("ATT_FLAG").to_numpy() == 1).astype(bool)
    sensors = [c for c in frame.columns if c[:2] in ("L_", "F_", "P_")]
    return times, frame[sensors].astype(float), labels


@dataclass(frozen=True)
class ResidualModel:
    columns: tuple[str, ...]
    mean: np.ndarray
    sd: np.ndarray
    basis: np.ndarray
    resid_mean: np.ndarray
    resid_sd: np.ndarray


def _standard(x: pd.DataFrame, mean: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return (x.to_numpy() - mean) / sd


def fit(train: pd.DataFrame, var_share: float = VAR_SHARE) -> ResidualModel:
    mean = train.to_numpy().mean(axis=0)
    sd = np.where(train.to_numpy().std(axis=0) > 0, train.to_numpy().std(axis=0), 1.0)
    z = _standard(train, mean, sd)
    _, s, vt = np.linalg.svd(z, full_matrices=False)
    share = np.cumsum(s**2) / np.sum(s**2)
    basis = vt[: int(np.searchsorted(share, var_share) + 1)]
    resid = z - z @ basis.T @ basis
    rsd = resid.std(axis=0)
    return ResidualModel(
        tuple(train.columns), mean, sd, basis, resid.mean(axis=0), np.where(rsd > 0, rsd, 1.0)
    )


def residual_z(model: ResidualModel, x: pd.DataFrame) -> np.ndarray:
    z = _standard(x[list(model.columns)], model.mean, model.sd)
    return (z - z @ model.basis.T @ model.basis - model.resid_mean) / model.resid_sd


def cusum_flags(rz: np.ndarray, h: float | None = None) -> np.ndarray:
    cfg = settings()
    h = cfg["cusum.h_sigma"] if h is None else h
    flags = np.zeros(rz.shape[0], dtype=bool)
    for j in range(rz.shape[1]):
        for _, alarm, last, _, _ in cusum_episodes(rz[:, j], cfg["cusum.k_sigma"], h):
            flags[alarm : last + 1] = True
    return flags


def calibrate_h(rz_train: np.ndarray, target: float = TRAIN_ALARM_TARGET) -> float:
    """Smallest h (bisection, 0.5 sigma steps) whose alarm share on the attack-free year is <= `target`."""
    lo, hi = settings()["cusum.h_sigma"], 4096.0
    while hi - lo > 0.5:
        mid = (lo + hi) / 2
        if cusum_flags(rz_train, mid).mean() <= target:
            hi = mid
        else:
            lo = mid
    return hi


def signature_flags(x: pd.DataFrame, times: pd.DatetimeIndex) -> np.ndarray:
    cfg = settings()
    t = (times - times[0]).total_seconds().to_numpy()
    flags = np.zeros(len(x), dtype=bool)
    for col in x.columns:
        v = x[col].to_numpy()
        if col.startswith(("L_", "P_")):
            run = int(cfg["frozen.level_run"] if col.startswith("L_") else cfg["frozen.pressure_run"])
            for a, b in frozen_runs(v, run, exclude_at_or_below=0.0):
                flags[a + run - 1 : b + 1] = True
        flags |= replay_hits(
            v,
            t,
            int(cfg["replay.window"]),
            cfg["replay.min_lag_h"] * HOUR_S,
            cfg["replay.max_lag_h"] * HOUR_S,
        )
    return flags


def limit_flags(train: pd.DataFrame, x: pd.DataFrame) -> np.ndarray:
    lo, hi = train.min().to_numpy(), train.max().to_numpy()
    v = x[train.columns].to_numpy()
    return ((v < lo) | (v > hi)).any(axis=1)


def zscore_flags(train: pd.DataFrame, x: pd.DataFrame, z: float = Z_BASELINE) -> np.ndarray:
    mean, sd = train.mean().to_numpy(), train.std().to_numpy()
    sd = np.where(sd > 0, sd, 1.0)
    return (np.abs((x[train.columns].to_numpy() - mean) / sd) >= z).any(axis=1)


def attack_windows(labels: np.ndarray) -> list[tuple[int, int]]:
    edges = np.diff(np.concatenate([[0], labels.astype(int), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1) - 1, strict=True))


def score(flags: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    windows = attack_windows(labels)
    ttd: list[float] = []
    detected = 0
    for a, b in windows:
        hit = np.flatnonzero(flags[a : b + 1])
        if len(hit):
            detected += 1
        ttd.append(round(float(hit[0]) / (b - a + 1), 4) if len(hit) else 1.0)
    tpr = float(flags[labels].mean())
    tnr = float((~flags[~labels]).mean())
    s_ttd = 1.0 - float(np.mean(ttd))
    s_clf = (tpr + tnr) / 2
    return {
        "attacks": len(windows),
        "attacks_detected": detected,
        "attack_hours": int(labels.sum()),
        "tpr": tpr,
        "tnr_lower_bound": tnr,
        "ttd_share_of_window": ttd,
        "s_ttd": s_ttd,
        "s_clf": s_clf,
        "s": (s_ttd + s_clf) / 2,
    }


def evaluate(raw_dir: Path) -> dict[str, Any]:
    _, train, _ = load(raw_dir / DATASET_TRAIN)
    t_test, test, labels = load(raw_dir / DATASET_TEST)
    t_train, _, _ = load(raw_dir / DATASET_TRAIN)
    model = fit(train)
    rz_train, rz_test = residual_z(model, train), residual_z(model, test)
    h_cal = calibrate_h(rz_train)
    residual = cusum_flags(rz_test)
    signature = signature_flags(test, t_test)
    methods = {
        "family_as_is": residual | signature,
        "residual_cusum_as_is": residual,
        "signatures_as_is": signature,
        "residual_cusum_h_recalibrated": cusum_flags(rz_test, h_cal),
        "static_limits": limit_flags(train, test),
        "zscore_4": zscore_flags(train, test),
    }
    train_share = {
        "family_as_is": float((cusum_flags(rz_train) | signature_flags(train, t_train)).mean()),
        "signatures_as_is": float(signature_flags(train, t_train).mean()),
        "residual_cusum_h_recalibrated": float(cusum_flags(rz_train, h_cal).mean()),
    }
    return {
        "components": int(model.basis.shape[0]),
        "sensors": len(model.columns),
        "test_hours": len(labels),
        "h_sigma_as_is": settings()["cusum.h_sigma"],
        "h_sigma_recalibrated": h_cal,
        "train_alarm_target": TRAIN_ALARM_TARGET,
        "train_alarm_share": train_share,
        "methods": {k: score(v, labels) for k, v in methods.items()},
    }


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_JSON = REPO_ROOT / "evals" / "reports" / "anomaly_batadal.json"
COMMAND = "uv run python -m sgw.models.anomaly.batadal --raw-dir raw/data/bench_water"
BASELINE = "static_limits"


def report(result: dict[str, Any], code_version: str) -> Any:
    from sgw.contracts.eval_report import EvalReport, MetricRow

    m = result["methods"]
    base = m[BASELINE]
    hours = result["test_hours"]
    rows = []
    for name in ("family_as_is", "residual_cusum_h_recalibrated"):
        r = m[name]
        rows.append(
            MetricRow(
                metric=f"anomaly_batadal.{name}.score_s",
                value=round(r["s"], 4),
                unit="BATADAL S = (S_TTD + S_CLF) / 2",
                n=r["attacks"],
                split="heldout",
                label="C",
                baseline_name="static SCADA limits from dataset03",
                baseline_value=round(base["s"], 4),
                threshold=round(base["s"], 4),
                direction="higher_is_better",
                passed=r["s"] >= base["s"],
            )
        )
        rows.append(
            MetricRow(
                metric=f"anomaly_batadal.{name}.tnr_lower_bound",
                value=round(r["tnr_lower_bound"], 4),
                unit="share of unlabelled hours without alarm",
                n=hours - r["attack_hours"],
                split="heldout",
                label="C",
                baseline_name="static SCADA limits from dataset03",
                baseline_value=round(base["tnr_lower_bound"], 4),
                threshold=round(base["tnr_lower_bound"], 4),
                direction="higher_is_better",
                passed=r["tnr_lower_bound"] >= base["tnr_lower_bound"],
            )
        )
    return EvalReport(
        name="anomaly_batadal",
        created_at=pd.Timestamp.now(tz="UTC").to_pydatetime().replace(microsecond=0),
        code_version=code_version,
        llm_mode="replay",
        command=COMMAND,
        metrics=rows,
    )


def main(argv: list[str] | None = None) -> None:
    import argparse
    import json

    from sgw.models.surge.fit import _git_version

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate(args.raw_dir)
    REPORT_JSON.write_text(report(result, _git_version()).model_dump_json(indent=2) + "\n", encoding="utf-8")
    detail = REPO_ROOT / "data" / "artefacts" / "surge" / "batadal_detail.json"
    detail.write_text(json.dumps(result, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1, default=float))


if __name__ == "__main__":
    main()
