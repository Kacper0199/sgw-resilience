"""A7/A8 dev report: helene fixture (seeded water faults) and the seeded dev bench. Dev split only; the
held-out family B is WP-15's and is never read here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sgw.common.telemetry import sgw_span
from sgw.contracts.vocab import Classification, EvalSplit, RunMode
from sgw.models.anomaly.detect import Alarm, baseline_alarms, detect, sensor_model, settings
from sgw.models.anomaly.devbench import BENCH_SEED, DAYS, bench_run
from sgw.models.anomaly.score import helene_truth, metrics, score
from sgw.models.anomaly.streams import from_fixture
from sgw.models.water.params import ARTEFACT_DIR, family
from sgw.models.water.twin import zone_twins

OUT_PATH = ARTEFACT_DIR / "anomaly_dev.json"
RECALL_TARGET = 0.8
FA_TARGET_PER_100 = 1.0


def _alarm_row(a: Alarm) -> dict[str, Any]:
    def iso(t: float) -> str:
        return datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "station": a.station,
        "family": a.family,
        "kind": a.kind,
        "devices": list(a.devices),
        "start_utc": iso(a.start),
        "detected_utc": iso(a.detected),
        "end_utc": iso(a.end),
        "detail": a.detail,
        "score": a.score,
    }


def anomaly_report(bench_days: int = 400, fixture: str = "helene") -> dict[str, Any]:
    fam = family()
    twins = zone_twins()
    sp, sl = fam.f("water.pressure_noise_psi"), fam.f("water.level_noise_ft")
    alarm_psi = fam.f("water.low_pressure_alarm_psi")
    results: dict[str, Any] = {}
    with sgw_span(
        "water.anomaly",
        run_id=f"water-anomaly-{fixture}",
        classification=Classification.C1,
        user_role="system",
        run_mode=RunMode.REPLAY,
        node="anomaly",
        region_id="SC-45003",
    ):
        streams = from_fixture(fixture)
        alarms = {
            s.station: detect(s, sensor_model(twins[s.station].pm, sp, sl, twins[s.station]), alarm_psi)
            for s in streams
        }
        days = sum(s.span_days for s in streams)
        truth = helene_truth(fixture)
        scored = score(alarms, truth, days)
        base = {
            s.station: baseline_alarms(
                s, sensor_model(twins[s.station].pm, sp, sl, twins[s.station]), alarm_psi
            )
            for s in streams
        }
        results["helene_dev"] = {
            "split": EvalSplit.DEV.value,
            "metrics": metrics(scored),
            "baseline_metrics": metrics(score(base, truth, days)),
            "faults": scored.faults,
            "false_alarms": scored.false_alarms,
            "alarms": [_alarm_row(a) for v in alarms.values() for a in v],
        }
        runs = [bench_run(i) for i in range(max(1, bench_days // DAYS))]
        m = sensor_model(twins["PS-52"].pm, sp, sl, twins["PS-52"])
        b_alarms = {r.run_id: detect(r.streams, m, alarm_psi) for r in runs}
        b_truth = {r.run_id: r.truth for r in runs}
        b_days = sum(r.streams.span_days for r in runs)
        b_scored = score(b_alarms, b_truth, b_days)
        b_base = {r.run_id: baseline_alarms(r.streams, m, alarm_psi) for r in runs}
        results["dev_bench"] = {
            "split": EvalSplit.DEV.value,
            "seed": BENCH_SEED,
            "runs": len(runs),
            "metrics": metrics(b_scored),
            "baseline_metrics": metrics(score(b_base, b_truth, b_days)),
            "missed": [f for f in b_scored.faults if not f["detected"]],
            "false_alarms": b_scored.false_alarms,
        }
    for block in results.values():
        mm = block["metrics"]
        fa_ok = mm["fa_per_100_asset_days"] <= FA_TARGET_PER_100
        block["passed_raw"] = bool(
            mm["recall"] >= RECALL_TARGET and fa_ok and mm["spoof_flagged"] == mm["spoof_cases"]
        )
        block["acceptance"] = "met on raw" if block["passed_raw"] else "not met on raw; WP-15 decides"
    return {
        "label": "synthetic",
        "split": EvalSplit.DEV.value,
        "command": "uv run sgw water anomaly",
        "targets": {
            "recall": RECALL_TARGET,
            "fa_per_100_asset_days": FA_TARGET_PER_100,
            "spoof": "all flagged",
        },
        "baseline": "station low-pressure alarm alone (water.low_pressure_alarm_psi; no A8, no status check)",
        "quoted_metric": "raw recall over every seeded fault (passed_raw); nothing else is a pass criterion",
        "post_hoc_subset": (
            "recall_physically_detectable and spoof_consequential are a post-hoc subset, defined after the "
            "first bench run from the true state with margins taken from the detector's own settings "
            "(0.5 / 1.5 ft level band, 4 windows before and 2 after a leak, 3 sigma for a replay); "
            "context only, never a pass"
        ),
        "limitations": [
            "replayed_sequence needs 8 equal readings: a 1.5-3 h level replay at 30-min sampling gives 3-6 "
            "readings, so steady-state level replays are missed; a 4-reading window would cost about "
            "0.07^4 x 336 lags x 48 windows = 0.4 chance matches per sensor-day (40 per 100 asset-days), "
            "far above the 1/100 target, so the window stays at 8 and this is a documented limitation",
            "a leak while the tank is held full by the pump changes neither pressure nor level; "
            "it needs flow metering",
            "pairwise A8 alarms cannot say which of the two sensors is wrong (except with a third sensor)",
        ],
        "settings": settings(),
        "sensor_noise": {"pressure_psi": sp, "level_ft": sl},
        "results": results,
    }
