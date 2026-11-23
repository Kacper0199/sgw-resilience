"""`sgw models ...`: hazard ensemble (A1), outage forecast (A2), LOSO backtest, risk publisher, plan diff and
no-regret shares."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

app = typer.Typer(name="models", help="Hazard ensemble, outage forecast, backtest, risk publisher.")

SCENARIO = Annotated[str, typer.Option(help="replay scenario under data/fixtures/")]
DATABASE = Annotated[str, typer.Option(help="database name (your own, e.g. sgw_wp11)")]
TICK = timedelta(minutes=15)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@app.command("eaglei-derive")
def eaglei_derive(
    raw_dir: Annotated[
        Path, typer.Option(help="folder with eaglei/ (EAGLE-I extracts, MCC.csv) and hurdat2/")
    ],
) -> None:
    """Rebuild data/open/eaglei/ (county x storm outage table and HURDAT2 tracks) from the raw extracts."""
    from sgw.models.outage.eaglei import derive

    hurdat = next((raw_dir / "hurdat2").glob("hurdat2-*.txt"))
    manifest = derive(raw_dir / "eaglei", hurdat)
    typer.echo(f"wrote {manifest['rows']} rows; outputs {json.dumps(manifest['outputs_sha256'])}")


@app.command("backtest-outage")
def backtest_outage() -> None:
    """Leave-one-storm-out on 4 real storms; writes evals/reports/outage_loso.json and the serving model."""
    from sgw.models.outage.backtest import REPORT_PATH, run_backtest

    result = run_backtest(write=True)
    typer.echo("hindcast, observed track (post-season best track of the held-out storm)")
    typer.echo(
        f"{'storm':<8} {'MAE m/b':>15} {'rho m/b':>11} {'cov80':>6} {'cov95':>6} "
        f"{'observed (uncapped)':>22} {'model':>10} {'rel':>5} {'base rel':>8} {'frag rel':>8}"
    )
    for s in result["detail"]["storms"]:
        m, b, f = s["model"], s["baseline"], s["fragility"]
        typer.echo(
            f"{s['storm']:<8} {m['county_mae_out']:>7,.0f}/{b['county_mae_out']:<7,.0f} "
            f"{m['spearman']:>5.2f}/{b['spearman'] or 0:<5.2f} "
            f"{m['coverage_80']:>6.2f} {m['coverage_95']:>6.2f} "
            f"{s['observed_total_out']:>10,} ({s['observed_total_out_uncapped']:>9,}) "
            f"{m['predicted_total_out']:>10,} "
            f"{m['rel_total_error']:>5.2f} {b['rel_total_error']:>8.2f} {f['rel_total_error']:>8.2f}"
        )
    wins = next(
        r
        for r in result["report"].metrics
        if r.metric.endswith("storms_model_beats_baseline_rel_total_error")
    )
    typer.echo(
        f"model beats the wind-threshold baseline on {wins.value:.0f} of {wins.n} storms "
        "(relative total error; 4 storms, no significance claim)"
    )
    typer.echo(f"wrote {REPORT_PATH}")


@app.command("backtest-outage-v2")
def backtest_outage_v2() -> None:
    """24-storm LOSO with pre-registered variants and nested selection; writes outage_loso_v2.json."""
    from sgw.models.outage.experiment import REPORT_V2, run_v2

    detail = run_v2(write=True)["detail"]
    typer.echo(
        "hindcast, observed track; S2 (nested selection, mostly the fitted fragility curve); customers"
    )
    typer.echo(
        f"{'storm':<11} {'observed':>10} {'S2 total':>10} {'rel':>5} "
        f"{'MAE S2/B1/B3':>22} {'cov80':>6} variant"
    )
    for r in detail["storms"]:
        m, b1, b3 = r["S2"], r["B1_wind_threshold"], r["B3_fragility_fitted"]
        typer.echo(
            f"{r['storm']:<11} {r['observed_total']:>10,} {m['predicted_total']:>10,} "
            f"{m['rel_total_error']:>5.2f} "
            f"{m['county_mae']:>6,.0f}/{b1['county_mae']:>6,.0f}/{b3['county_mae']:>6,.0f} "
            f"{m['coverage_80']:>6.2f} {m['variant']}"
        )
    pre = detail["summary_all"]["S"]
    typer.echo(
        f"pre-registered S (model): beats wind threshold on county MAE in "
        f"{pre['beats_B1_wind_threshold_county_mae']} storms, "
        f"median ratio {pre['median_mae_ratio_vs_B1']:.2f}"
    )
    vs = detail["summary_all"]["S2_vs_B3_county_mae"]
    typer.echo(
        f"S2 vs fitted fragility: same {vs['same']}, better {vs['better']}, worse {vs['worse']}, "
        f"Wilcoxon p {vs['wilcoxon_p_untied']}"
    )
    s = detail["summary_all"]["S2"]
    typer.echo(
        f"S2 beats wind threshold on county MAE in {s['beats_B1_wind_threshold_county_mae']} of "
        f"{detail['summary_all']['storms']} storms; "
        f"fitted fragility in {s['beats_B3_fragility_fitted_county_mae']}"
    )
    c = detail["serving_candidate"]
    typer.echo(
        f"serving candidate (storms before Helene): {c['variant']} "
        f"w={c['weight_model']} {c['interval_space']}"
    )
    typer.echo(f"wrote {REPORT_V2}")


@app.command("backtest-outage-v3")
def backtest_outage_v3() -> None:
    """Pre-registered v3 experiments (GLM, boosted residual, wind calibration); writes outage_loso_v3.json."""
    from sgw.models.outage.experiment_v3 import main

    main()


@app.command("hazard-check")
def hazard_check(advisory: Annotated[str, typer.Option()] = "N+1", scenario: SCENARIO = "helene") -> None:
    """A1 wind-profile check (not forecast skill): member spread vs observed ASOS peak gusts."""
    from sgw.models.hazard.validation import station_check

    result = station_check(advisory, scenario)
    for s in result["stations"]:
        flag = "censored" if s["censored"] else ("inside" if s["inside_spread"] else "OUTSIDE")
        typer.echo(
            f"{s['station']} observed {s['observed_ms']:5.1f} m/s  members {s['member_min_ms']:5.1f}-"
            f"{s['member_max_ms']:5.1f} (P50 {s['member_p50_ms']:5.1f})  {flag}"
        )
    typer.echo(f"{result['inside_spread']} of {result['stations_scored']} scored stations inside the spread")


def _risk(scenario: str, advisory: str) -> Any:
    from sgw.models.outage.forecast import advisory_risk

    return advisory_risk(scenario, advisory)


@app.command("risk")
def risk(
    advisory: Annotated[str, typer.Option(help="advisory label, e.g. N+1")], scenario: SCENARIO = "helene"
) -> None:
    """Print the county fans, top assets and no-regret shares of one advisory (no database)."""
    r = _risk(scenario, advisory)
    c = r.counties.sort_values("mean_out", ascending=False).head(10)
    typer.echo(f"{scenario} {advisory} ({r.forecast_id}, issued {r.issued_utc}); model {r.model_name}")
    for row in c.itertuples():
        typer.echo(
            f"  {row.fips} {row.name:<14} P50 {row.q0500_out:>7,}  "
            f"80% {row.q0100_out:>7,}-{row.q0900_out:<7,} 95% {row.q0025_out:>7,}-{row.q0975_out:<7,} "
            f"p(>=10%) {row.p_ppm / 1e6:.2f} {row.band}"
        )
    for a in r.actions:
        typer.echo(
            f"  {a.action_id:<28} no-regret share {a.share_ppm / 1e6:.3f} ({a.members_needed}/{a.members})"
        )


@app.command("no-regret")
def no_regret(advisory: Annotated[str, typer.Option()], scenario: SCENARIO = "helene") -> None:
    """No-regret share per action: fraction of ensemble members in which the action is needed."""
    r = _risk(scenario, advisory)
    typer.echo(json.dumps([a.__dict__ for a in r.actions], indent=2, default=list))


@app.command("plan-diff")
def plan_diff_cmd(
    from_advisory: Annotated[str, typer.Option("--from")] = "N",
    to_advisory: Annotated[str, typer.Option("--to")] = "N+1",
    scenario: SCENARIO = "helene",
) -> None:
    """What changed between two advisories: county fans, asset bands, no-regret shares."""
    from sgw.models.outage.plan_diff import plan_diff

    typer.echo(json.dumps(plan_diff(_risk(scenario, from_advisory), _risk(scenario, to_advisory)), indent=2))


def _scenario_now(conn: Any) -> tuple[str, datetime] | None:
    from sgw.api.clock import ClockState, scenario_def

    row = conn.execute("SELECT scenario_clock FROM control_state WHERE id = 1").fetchone()
    if not row or not row[0]:
        return None
    state = ClockState.from_json(row[0])
    return state.scenario, state.scenario_now(datetime.now(tz=UTC), scenario_def(state.scenario))


@app.command("publish-risk")
def publish_risk(
    database: DATABASE,
    at: Annotated[
        str | None, typer.Option(help="scenario time (UTC ISO); default: the scenario clock")
    ] = None,
    scenario: SCENARIO = "helene",
    follow: Annotated[bool, typer.Option(help="keep publishing on every 15-min scenario tick")] = False,
    poll_s: Annotated[float, typer.Option(help="clock poll interval in follow mode")] = 2.0,
) -> None:
    """Publish RiskSnapshotPublished (snapshot, risk, forecast, plan diff) for a scenario tick."""
    from sgw.ingest.db import connect, database_url
    from sgw.models.outage.publisher import publish_tick

    conn = connect(database_url(database))
    last_tick: datetime | None = None
    while True:
        if at is not None:
            name, when = scenario, _utc(at)
        else:
            found = _scenario_now(conn)
            if found is None:
                typer.echo("no scenario clock in control_state; pass --at", err=True)
                raise typer.Exit(2)
            name, when = found
        tick = datetime.fromtimestamp(
            (when.timestamp() // TICK.total_seconds()) * TICK.total_seconds(), tz=UTC
        )
        if tick != last_tick:
            result = publish_tick(conn, tick, name)
            typer.echo(
                f"{tick:%Y-%m-%dT%H:%MZ} advisory {result.advisory_label} snapshot {result.snapshot_id} "
                f"seq {result.event_seq} new={result.created} {result.seconds:.2f}s"
            )
            last_tick = tick
        if not follow or at is not None:
            return
        time.sleep(poll_s)
