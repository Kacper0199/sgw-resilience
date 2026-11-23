"""Fit and evaluate the outage-surge detector on EAGLE-I 2016-2025 against NCEI Storm Events (G1).

Time split: every setting is chosen on the train seasons 2016-2021 only; the test seasons 2022-2025 (2024 is
Aug-Oct, the only 2024 extract on disk) are scored once with the chosen settings. Each method (the model and
both baselines) gets the same search: the setting with the highest train recall within `FA_BUDGET` false
alarms per county-month. The canonical baselines (1% of customers out; rolling z >= 4) are reported as well.
Unit: the 123 footprint counties. The first `WARMUP_H` of a season (rolling baseline not ready) is not scored.

Run: `uv run python -m sgw.models.surge.fit --raw-dir <raw/data>` (writes the report, model card numbers and
the artefacts under `data/artefacts/surge/`).
"""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sgw.generator.config import load_counties
from sgw.models.outage.eaglei import read_mcc
from sgw.models.surge.confidence import fit as fit_confidence
from sgw.models.surge.confidence import predict
from sgw.models.surge.detect import (
    CusumParams,
    FixedShareParams,
    Params,
    RollingZParams,
    Surge,
    cusum_start,
    cusum_statistic,
    gate,
    global_gap,
    log_stats,
    rolling_z_start,
    rolling_z_stat,
    segment,
    start_condition,
)
from sgw.models.surge.evaluate import FA_BUDGET_DEFAULT, choose, match, paired_bootstrap, summarise
from sgw.models.surge.labels import county_events
from sgw.models.surge.series import Season, county_names, season_matrix, seasons

TRAIN_YEARS = (2016, 2017, 2018, 2019, 2020, 2021)
TEST_YEARS = (2022, 2023, 2024, 2025)
WARMUP_H = 72.0
FA_BUDGET = FA_BUDGET_DEFAULT
DAYS_PER_MONTH = 30.4375
WINDOW_H = 168.0
CONCURRENCY_H = 3.0


@dataclass
class SeasonData:
    season: Season
    times: pd.DatetimeIndex
    x: np.ndarray
    stats: tuple[np.ndarray, np.ndarray]

    @property
    def scored_from(self) -> pd.Timestamp:
        return self.season.start + timedelta(hours=WARMUP_H)


@dataclass
class Corpus:
    fips: list[str]
    mcc: np.ndarray
    names: dict[str, tuple[str, str]]
    events: pd.DataFrame
    unmatched_zones: dict[str, int]
    data: dict[int, SeasonData]
    hashes: dict[str, str]
    cache: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    zcache: dict[tuple[Any, ...], Any] = field(default_factory=dict)

    def county_months(self, years: tuple[int, ...]) -> float:
        days = sum(
            (self.data[y].season.end - self.data[y].scored_from).total_seconds() / 86400 for y in years
        )
        return len(self.fips) * days / DAYS_PER_MONTH


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_corpus(raw_dir: Path) -> Corpus:
    fips = [c.fips for c in load_counties()]
    mcc_map = read_mcc(raw_dir / "eaglei" / "MCC.csv")
    mcc = np.array([float(mcc_map[f]) for f in fips])
    season_list = seasons(raw_dir / "eaglei")
    names = county_names(season_list[-1].path)
    storm_files = sorted((raw_dir / "storm_events").glob("StormEvents_details-ftp_v1.0_d*.csv.gz"))
    events, unmatched = county_events(storm_files, names)
    events = events[events["fips"].isin(fips)].reset_index(drop=True)
    data: dict[int, SeasonData] = {}
    for s in season_list:
        times, x = season_matrix(s.path, fips, s.start, s.end)
        data[s.year] = SeasonData(s, times, x, log_stats(x, WINDOW_H))
    files = [s.path for s in season_list] + storm_files + [raw_dir / "eaglei" / "MCC.csv"]
    return Corpus(fips, mcc, names, events, unmatched, data, {p.name: sha256(p) for p in files})


def _season_surges(corpus: Corpus, sd: SeasonData, params: Params) -> list[Surge]:
    if isinstance(params, CusumParams):
        key = ("cusum", sd.season.year, params.k, params.h, params.scale_floor)
        if key not in corpus.cache:
            corpus.cache[key] = cusum_statistic(sd.x, params, sd.stats)
        stat, level, onset = corpus.cache[key]
        start = cusum_start(stat, level, sd.x, gate(params, corpus.mcc), params)
    elif isinstance(params, RollingZParams):
        key = ("z", sd.season.year)
        if key not in corpus.zcache:
            corpus.zcache[key] = rolling_z_stat(sd.x, params.window_h)
        stat = corpus.zcache[key]
        level = np.expm1(sd.stats[0])
        onset = np.arange(len(sd.times))[:, None].repeat(len(corpus.fips), axis=1)
        start = rolling_z_start(stat, level, sd.x, gate(params, corpus.mcc), params)
    else:
        start, level, onset, stat = start_condition(sd.x, corpus.mcc, params, sd.stats)
    return segment(
        start,
        sd.x,
        level,
        corpus.mcc,
        sd.times,
        onset=onset,
        gap=global_gap(sd.x),
        end_h=params.end_h,
        gate_customers=gate(params, corpus.mcc),
        stat=stat,
    )


def surge_frame(corpus: Corpus, params: Params, years: tuple[int, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for y in years:
        sd = corpus.data[y]
        for s in _season_surges(corpus, sd, params):
            if s.detected_at < sd.scored_from:
                continue
            row = asdict(s)
            row["fips"] = corpus.fips[s.county]
            row["year"] = y
            row["dq_flags"] = "|".join(s.dq_flags)
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["fips", "year", "detected_at", "excess_share_detect", "statistic"])
    frame["concurrent"] = concurrency(frame["fips"], frame["detected_at"])
    return frame


def concurrency(fips: pd.Series, detected: pd.Series, as_of: pd.Timestamp | None = None) -> np.ndarray:
    """Other counties with a surge detected within +-`CONCURRENCY_H` (and not after `as_of`)."""
    t = pd.DatetimeIndex(detected).as_unit("ns").asi8
    f = fips.to_numpy()
    w = int(CONCURRENCY_H * 3_600_000_000_000)
    limit = np.iinfo(np.int64).max if as_of is None else pd.Timestamp(as_of).as_unit("ns").value
    out = np.zeros(len(t), dtype=np.int64)
    order = np.argsort(t)
    ts = t[order]
    for i, ti in enumerate(t):
        lo = np.searchsorted(ts, ti - w, "left")
        hi = np.searchsorted(ts, min(ti + w, limit), "right")
        others = set(f[order[lo:hi]]) - {f[i]}
        out[i] = len(others)
    return out


def scored_events(corpus: Corpus, years: tuple[int, ...]) -> pd.DataFrame:
    keep = np.zeros(len(corpus.events), dtype=bool)
    for y in years:
        sd = corpus.data[y]
        keep |= (
            (corpus.events["begin"] >= sd.scored_from) & (corpus.events["begin"] < sd.season.end)
        ).to_numpy()
    return corpus.events[keep].reset_index(drop=True)


def score(corpus: Corpus, params: Params, years: tuple[int, ...]) -> dict[str, Any]:
    surges = surge_frame(corpus, params, years)
    events, matched = match(scored_events(corpus, years), surges)
    out = summarise(events, matched, corpus.county_months(years))
    out["_events"], out["_surges"] = events, matched
    return out


def grids() -> dict[str, list[Params]]:
    """Search grids. `fixed_share_corroborated` is the ablation: the model's spatial rule on the baseline."""
    gates = list(
        itertools.product((250.0, 500.0, 750.0, 1000.0, 1500.0, 2000.0), (0.0025, 0.005, 0.01, 0.02))
    )
    cusum = [
        CusumParams(
            window_h=WINDOW_H, k=k, h=h, scale_floor=0.35, min_customers=c, min_share=s, corroborate=co
        )
        for co, k, h in itertools.product((0, 2, 4, 6), (0.5, 1.0, 2.0), (4.0, 8.0, 16.0))
        for c, s in gates
    ]
    rolling = [
        RollingZParams(window_h=WINDOW_H, z=z, min_customers=c, min_share=s)
        for z in (3.0, 4.0, 6.0, 8.0, 12.0)
        for c, s in gates
    ]
    shares = (0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.1, 0.12, 0.15, 0.2)
    fixed = [FixedShareParams(window_h=WINDOW_H, share=s) for s in shares]
    ablation = [
        FixedShareParams(window_h=WINDOW_H, share=s, corroborate=co) for co in (2, 4, 6) for s in shares
    ]
    return {
        "robust_cusum": cusum,
        "rolling_z": rolling,
        "fixed_share": fixed,
        "fixed_share_corroborated": ablation,
    }


CANONICAL: dict[str, Params] = {
    "fixed_share_1pct": FixedShareParams(window_h=WINDOW_H, share=0.01),
    "rolling_z_4": RollingZParams(window_h=WINDOW_H, z=4.0),
}


def public(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in metrics.items() if not k.startswith("_")}


def params_dict(p: Params) -> dict[str, Any]:
    return {"method": p.method, **asdict(p)}


def params_from(d: dict[str, Any]) -> Params:
    kinds: dict[str, type[Params]] = {
        "robust_cusum": CusumParams,
        "fixed_share": FixedShareParams,
        "rolling_z": RollingZParams,
    }
    body = {k: v for k, v in d.items() if k != "method"}
    return kinds[d["method"]](**body)


def with_window(p: Params, window_h: float) -> Params:
    return replace(p, window_h=window_h)


def search(corpus: Corpus, candidates: list[Params], years: tuple[int, ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_key: tuple[Any, ...] | None = None
    for p in candidates:
        key = (p.method, getattr(p, "k", None), getattr(p, "h", None), getattr(p, "scale_floor", None))
        if key != last_key:
            corpus.cache.clear()
            last_key = key
        m = score(corpus, p, years)
        rows.append({"params": p, **{k: v for k, v in public(m).items() if k != "by_tier"}})
    corpus.cache.clear()
    return rows


def recall_ci(events: pd.DataFrame, reps: int = 2000, seed: int = 20261121) -> tuple[float, float]:
    hit = events["detected"].to_numpy(dtype=float)
    _, low, high = paired_bootstrap(hit, np.zeros_like(hit), events["begin"], reps=reps, seed=seed)
    return low, high


def helene(corpus: Corpus, params: Params, coefs: dict[str, Any]) -> dict[str, Any]:
    sd = corpus.data[2024]
    frame = surge_frame(corpus, params, (2024,))
    lo, hi = pd.Timestamp("2024-09-25", tz="UTC"), pd.Timestamp("2024-09-30", tz="UTC")
    win = frame[(frame["detected_at"] >= lo) & (frame["detected_at"] < hi)].copy()
    win["confidence"] = predict(coefs, win["excess_share_detect"].to_numpy(), win["concurrent"].to_numpy())
    events = scored_events(corpus, (2024,))
    events = events[(events["begin"] >= lo) & (events["begin"] < hi)]
    matched_events, _ = match(events, frame)
    hours = win["detected_at"].dt.floor("h").value_counts().sort_index().cumsum()
    first = win["detected_at"].min() if len(win) else None
    n = win["fips"].nunique()
    reach = {}
    for share in (0.5, 0.9):
        need = int(np.ceil(share * n))
        firsts = win.groupby("fips")["detected_at"].min().sort_values()
        reach[f"{int(share * 100)}pct_of_surging_counties_by"] = (
            firsts.iloc[need - 1].isoformat() if n else None
        )
    storm_counties = sd.x.shape[1]
    tropical = matched_events[matched_events["tier"] == "tropical"]
    return {
        "window_utc": [lo.isoformat(), hi.isoformat()],
        "counties_monitored": storm_counties,
        "counties_with_surge": int(n),
        "surges": len(win),
        "first_detected_at": first.isoformat() if first is not None else None,
        **reach,
        "cumulative_surges_by_hour_utc": {t.isoformat(): int(v) for t, v in hours.items()},
        "ncei_label_events": len(matched_events),
        "ncei_recall": float(matched_events["detected"].mean()) if len(matched_events) else None,
        "ncei_tropical_events": len(tropical),
        "ncei_tropical_recall": float(tropical["detected"].mean()) if len(tropical) else None,
        "delay_h_median": float(matched_events["delay_h"].median()) if len(matched_events) else None,
        "confidence_median": float(win["confidence"].median()) if len(win) else None,
        "high_confidence_surges": int((win["confidence"] >= coefs["bands"]["high"]).sum()),
    }


REPO_ROOT = Path(__file__).resolve().parents[4]
ARTEFACT_DIR = REPO_ROOT / "data" / "artefacts" / "surge"
PARAMS_JSON = ARTEFACT_DIR / "params.json"
HELENE_SERIES = ARTEFACT_DIR / "helene_series.csv.gz"
REPORT_JSON = REPO_ROOT / "evals" / "reports" / "outage_surge.json"
DETAIL_JSON = ARTEFACT_DIR / "eval_detail.json"
COMMAND = "uv run python -m sgw.models.surge.fit --raw-dir raw/data"
CURVE_BUDGETS = (0.10, 0.25, 0.50)
NO_CORROBORATION = "robust_cusum_no_corroboration"
BASELINES = ("fixed_share", "rolling_z")
ABLATIONS = ("fixed_share_corroborated", NO_CORROBORATION)
MODEL_VERSION = "surge-cusum-v1"
SOURCE = (
    "EAGLE-I county customers out, 15-min (ORNL, figshare doi:10.6084/m9.figshare.24237376.v4, CC BY 4.0); "
    "labels NCEI Storm Events (public domain)"
)


def _git_version() -> str:
    import subprocess

    try:
        return subprocess.run(  # noqa: S603
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_round(x) for x in v]
    return v


def _row(params: Params, metrics: dict[str, Any]) -> dict[str, Any]:
    return _round(
        {"params": params_dict(params), **{k: v for k, v in metrics.items() if not k.startswith("_")}}
    )


def run(raw_dir: Path, *, write: bool = True) -> dict[str, Any]:
    from sklearn.metrics import roc_auc_score

    from sgw.contracts.eval_report import EvalReport, MetricRow
    from sgw.models.surge.series import HELENE_SERIES_END, HELENE_SERIES_START, write_series

    corpus = load_corpus(raw_dir)
    grid = grids()
    train_rows = {m: search(corpus, grid[m], TRAIN_YEARS) for m in grid}
    train_rows[NO_CORROBORATION] = [r for r in train_rows["robust_cusum"] if r["params"].corroborate == 0]
    curve: dict[str, dict[str, Any]] = {}
    chosen: dict[str, Params] = {}
    for budget in CURVE_BUDGETS:
        for m, rows in train_rows.items():
            if budget != FA_BUDGET and not any(r["false_alarms_per_county_month"] <= budget for r in rows):
                curve.setdefault(f"{budget:.2f}", {})[m] = None
                continue
            pick = choose(rows, budget)
            if budget == FA_BUDGET:
                chosen[m] = pick["params"]
            test = public(score(corpus, pick["params"], TEST_YEARS))
            curve.setdefault(f"{budget:.2f}", {})[m] = _round(
                {
                    "params": params_dict(pick["params"]),
                    "train_recall": pick["recall"],
                    "train_fa": pick["false_alarms_per_county_month"],
                    "test_recall": test["recall"],
                    "test_fa": test["false_alarms_per_county_month"],
                    "test_delay_h_median": test["delay_h_median"],
                }
            )
    model = chosen["robust_cusum"]
    train = {m: score(corpus, p, TRAIN_YEARS) for m, p in chosen.items()}
    test = {m: score(corpus, p, TEST_YEARS) for m, p in chosen.items()}
    canonical = {m: score(corpus, p, TEST_YEARS) for m, p in CANONICAL.items()}
    hits = {m: r["_events"]["detected"].to_numpy() for m, r in {**test, **canonical}.items()}
    days = test["robust_cusum"]["_events"]["begin"]
    contrasts = {}
    for b in (*BASELINES, *ABLATIONS, *CANONICAL):
        d, lo, hi = paired_bootstrap(hits["robust_cusum"], hits[b], days)
        fa_m = test["robust_cusum"]["false_alarms_per_county_month"]
        fa_b = (test.get(b) or canonical[b])["false_alarms_per_county_month"]
        contrasts[b] = _round(
            {
                "recall_diff": d,
                "ci_low": lo,
                "ci_high": hi,
                "fa_model": fa_m,
                "fa_baseline": fa_b,
                "beats": bool(lo > 0 and fa_m <= fa_b),
            }
        )
    beats = all(contrasts[b]["beats"] for b in BASELINES)
    tr_s, te_s = train["robust_cusum"]["_surges"], test["robust_cusum"]["_surges"]
    coefs = fit_confidence(tr_s["excess_share_detect"], tr_s["concurrent"], tr_s["explained"])
    p_test = predict(coefs, te_s["excess_share_detect"].to_numpy(), te_s["concurrent"].to_numpy())
    y_test = te_s["explained"].to_numpy(dtype=float)
    base_rate = float(tr_s["explained"].mean())
    conf = _round(
        {
            **coefs,
            "train_surges": len(tr_s),
            "train_base_rate": base_rate,
            "test_surges": len(te_s),
            "test_brier": float(np.mean((p_test - y_test) ** 2)),
            "test_brier_base_rate": float(np.mean((base_rate - y_test) ** 2)),
            "test_auc": float(roc_auc_score(y_test, p_test)),
            "test_explained_share_by_band": {
                name: float(y_test[mask].mean()) if mask.any() else None
                for name, mask in (
                    ("high", p_test >= coefs["bands"]["high"]),
                    ("medium", (p_test >= coefs["bands"]["medium"]) & (p_test < coefs["bands"]["high"])),
                    ("low", p_test < coefs["bands"]["medium"]),
                )
            },
        }
    )
    hel = _round(helene(corpus, model, coefs))
    hel_base = {b: _round(helene(corpus, chosen[b], coefs)) for b in BASELINES}
    best_hel = max(BASELINES, key=lambda b: hel_base[b]["ncei_tropical_recall"] or 0.0)
    by_year = {y: _round(public(score(corpus, model, (y,)))) for y in TEST_YEARS}
    tm, tb1, tb2 = (public(test[m]) for m in ("robust_cusum", "fixed_share", "rolling_z"))
    best_b = max((tb1, tb2), key=lambda r: r["recall"])
    lo, hi = recall_ci(test["robust_cusum"]["_events"])
    n_ev, n_sg = tm["events"], max(tm["surges"], 1)
    worst_delay = max(tb1["delay_h_median"], tb2["delay_h_median"])
    rows = [
        MetricRow(
            metric="outage_surge.test.event_recall",
            value=round(tm["recall"], 4),
            unit="share of NCEI wind episodes",
            n=n_ev,
            split="heldout",
            label="C",
            baseline_name="best tuned baseline (fixed share or rolling z)",
            baseline_value=round(best_b["recall"], 4),
            threshold=round(best_b["recall"], 4),
            direction="higher_is_better",
            passed=tm["recall"] >= best_b["recall"],
            ci_low=round(min(lo, tm["recall"]), 4),
            ci_high=round(max(hi, tm["recall"]), 4),
        ),
        MetricRow(
            metric="outage_surge.test.recall_diff_vs_fixed_share",
            value=contrasts["fixed_share"]["recall_diff"],
            unit="recall difference, paired by event day",
            n=n_ev,
            split="heldout",
            label="C",
            baseline_name="tuned fixed share",
            baseline_value=0.0,
            threshold=0.0,
            direction="higher_is_better",
            passed=contrasts["fixed_share"]["recall_diff"] >= 0.0,
            ci_low=contrasts["fixed_share"]["ci_low"],
            ci_high=contrasts["fixed_share"]["ci_high"],
        ),
        MetricRow(
            metric="outage_surge.test.recall_diff_vs_rolling_z",
            value=contrasts["rolling_z"]["recall_diff"],
            unit="recall difference, paired by event day",
            n=n_ev,
            split="heldout",
            label="C",
            baseline_name="tuned rolling z",
            baseline_value=0.0,
            threshold=0.0,
            direction="higher_is_better",
            passed=contrasts["rolling_z"]["recall_diff"] >= 0.0,
            ci_low=contrasts["rolling_z"]["ci_low"],
            ci_high=contrasts["rolling_z"]["ci_high"],
        ),
        MetricRow(
            metric="outage_surge.test.false_alarms_per_county_month",
            value=round(tm["false_alarms_per_county_month"], 4),
            unit="surges matching no NCEI event per county-month",
            n=max(int(tm["county_months"]), 1),
            split="heldout",
            label="C",
            baseline_name="best tuned baseline",
            baseline_value=round(best_b["false_alarms_per_county_month"], 4),
            threshold=FA_BUDGET * 1.2,
            direction="lower_is_better",
            passed=tm["false_alarms_per_county_month"] <= FA_BUDGET * 1.2,
        ),
        MetricRow(
            metric="outage_surge.test.delay_h_median",
            value=round(tm["delay_h_median"], 4),
            unit="h from NCEI begin to detection (detected episodes)",
            n=max(tm["detected"], 1),
            split="heldout",
            label="C",
            baseline_name="best tuned baseline",
            baseline_value=round(best_b["delay_h_median"], 4),
            threshold=round(worst_delay, 4),
            direction="lower_is_better",
            passed=tm["delay_h_median"] <= worst_delay,
        ),
        MetricRow(
            metric="outage_surge.test.precision_lower_bound",
            value=round(tm["precision"], 4),
            unit="share of surges matching an NCEI event",
            n=n_sg,
            split="heldout",
            label="C",
            baseline_name="best tuned baseline",
            baseline_value=round(best_b["precision"], 4),
            threshold=round(min(tb1["precision"], tb2["precision"]), 4),
            direction="higher_is_better",
            passed=tm["precision"] >= min(tb1["precision"], tb2["precision"]),
        ),
        MetricRow(
            metric="outage_surge.test.confidence_brier",
            value=conf["test_brier"],
            unit="Brier score",
            n=max(conf["test_surges"], 1),
            split="heldout",
            label="C",
            baseline_name="train base rate",
            baseline_value=conf["test_brier_base_rate"],
            threshold=conf["test_brier_base_rate"],
            direction="lower_is_better",
            passed=conf["test_brier"] <= conf["test_brier_base_rate"],
        ),
    ]
    if hel["ncei_tropical_recall"] is not None:
        rows.append(
            MetricRow(
                metric="outage_surge.helene.tropical_episode_recall",
                value=hel["ncei_tropical_recall"],
                unit="share of NCEI Helene tropical county episodes",
                n=max(hel["ncei_tropical_events"], 1),
                split="heldout",
                label="C",
                baseline_name=f"tuned {best_hel.replace('_', ' ')} (same window)",
                baseline_value=hel_base[best_hel]["ncei_tropical_recall"],
                threshold=hel_base[best_hel]["ncei_tropical_recall"],
                direction="higher_is_better",
                passed=hel["ncei_tropical_recall"] >= hel_base[best_hel]["ncei_tropical_recall"],
            )
        )
    report = EvalReport(
        name="outage_surge",
        created_at=pd.Timestamp.now(tz="UTC").to_pydatetime().replace(microsecond=0),
        code_version=_git_version(),
        llm_mode="replay",
        command=COMMAND,
        metrics=rows,
    )
    detail = {
        "name": "outage_surge_detail",
        "model_version": MODEL_VERSION,
        "label": "C: computed on public EAGLE-I and NCEI data; not utility figures",
        "source": SOURCE,
        "split": {"train": list(TRAIN_YEARS), "test": list(TEST_YEARS), "note": "2024 = Aug-Oct only"},
        "counties": len(corpus.fips),
        "fa_budget_per_county_month": FA_BUDGET,
        "match_window_h": {"pre": 3.0, "post": 12.0},
        "beats_both_tuned_baselines": beats,
        "contrasts": contrasts,
        "chosen": {m: params_dict(p) for m, p in chosen.items()},
        "train": {m: _row(chosen[m], r) for m, r in train.items()},
        "test": {m: _row(chosen[m], r) for m, r in test.items()},
        "test_canonical": {m: _row(CANONICAL[m], r) for m, r in canonical.items()},
        "test_model_by_year": by_year,
        "operating_curve": curve,
        "grid_sizes": {m: len(v) for m, v in grid.items()},
        "confidence": conf,
        "helene": hel,
        "helene_baselines": {
            b: {k: v for k, v in r.items() if k != "cumulative_surges_by_hour_utc"}
            for b, r in hel_base.items()
        },
        "unmatched_zone_names": corpus.unmatched_zones,
        "data_sha256": corpus.hashes,
    }
    params_out = {
        "model_version": MODEL_VERSION,
        "source": SOURCE,
        "fitted_on": list(TRAIN_YEARS),
        "params": params_dict(model),
        "confidence": coefs,
        "counties": [
            {"fips": c.fips, "name": c.name, "st": c.st, "mcc": int(m)}
            for c, m in zip(load_counties(), corpus.mcc, strict=True)
        ],
        "code_version": report.code_version,
        "report": "evals/reports/outage_surge.json",
    }
    if write:
        sd = corpus.data[2024]
        keep = (sd.times >= HELENE_SERIES_START) & (sd.times < HELENE_SERIES_END)
        ARTEFACT_DIR.mkdir(parents=True, exist_ok=True)
        write_series(HELENE_SERIES, sd.times[keep], sd.x[keep], corpus.fips)
        write_outputs(report.model_dump_json(indent=2), detail, params_out)
    return {"report": report, "detail": detail, "params": params_out}


def write_outputs(report_json: str, detail: dict[str, Any], params_out: dict[str, Any]) -> None:
    ARTEFACT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(report_json + "\n", encoding="utf-8")
    DETAIL_JSON.write_text(json.dumps(detail, indent=2, default=str) + "\n", encoding="utf-8")
    PARAMS_JSON.write_text(json.dumps(params_out, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    out = run(args.raw_dir, write=not args.dry_run)
    d = out["detail"]
    keys = ("beats_both_tuned_baselines", "contrasts", "chosen", "confidence", "helene")
    print(json.dumps({k: d[k] for k in keys}, indent=1, default=str))
    print(
        json.dumps({m: {k: v for k, v in r.items() if k != "params"} for m, r in d["test"].items()}, indent=1)
    )


if __name__ == "__main__":
    main()
