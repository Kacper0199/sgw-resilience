"""`sgw restoration calibrate|eval|etr`: restoration process and the A6 ETR model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(name="restoration", help="Restoration process and ETR (A6).", no_args_is_help=True)


@app.command("calibrate")
def calibrate(
    write: Annotated[bool, typer.Option(help="print the fitted values for params.yaml")] = True,
) -> None:
    """Fit section_scale and secondary_per_100 to the EAGLE-I Helene county medians t50, t90 (~10 min)."""
    from sgw.models.restoration import calibrate as cal
    from sgw.models.restoration.params import default_params

    obs = cal.load_observed()
    prm, trace = cal.fit(cal.calibration_worlds(), default_params(), obs)
    for row in trace:
        typer.echo(json.dumps({k: round(v, 4) for k, v in row.items()}), err=False)
    if write:
        fitted = " ".join(f"process.{k} {prm.f('process', k)}" for k in cal.FIT_KEYS)
        typer.echo(f"params.yaml {fitted}")


@app.command("eval")
def evaluate(
    workers: Annotated[int, typer.Option(help="worker processes")] = 2,
    limit: Annotated[int | None, typer.Option(help="storms per split (smoke runs only)")] = None,
    out: Annotated[Path | None, typer.Option(help="report path (default evals/reports/etr.json)")] = None,
) -> None:
    """Helene calibration report + family-A coverage; writes the K17 report and the serving artefact."""
    from sgw.models.restoration import artefact, report
    from sgw.models.restoration.calibrate import load_observed, targets
    from sgw.models.restoration.calibrate import report as cal_report
    from sgw.models.restoration.evaluate import evaluate as run_eval

    analog_t90 = float(targets(load_observed())[1])
    cal = cal_report()
    ev = run_eval(analog_t90, workers=workers, limit=limit)
    rep = report.build(ev, cal)
    path = report.write(rep, out or report.REPORT_PATH)
    if limit is None:
        artefact.save(ev.model, ev.calibrators)
    typer.echo(f"wrote {path}")
    for sc in ev.scores:
        typer.echo(
            f"{sc.population} +{sc.offset_h:.0f}h: cov80 {sc.coverage80:.3f} wilson "
            f"[{sc.coverage80_wilson[0]:.3f}, {sc.coverage80_wilson[1]:.3f}] "
            f"band x0.9 {sc.coverage80_shrunk10:.3f} "
            f"x1.1 {sc.coverage80_widened10:.3f}; width80 {sc.width80_median_h:.1f} h, width50 "
            f"{sc.width50_median_h:.1f} h; cov50 {sc.coverage50:.3f}; n {sc.n}"
        )
    for m in rep.metrics:
        ci = f" [{m.ci_low}, {m.ci_high}]" if m.ci_low is not None else ""
        verdict = "pass" if m.passed else "FAIL"
        typer.echo(
            f"{verdict:4} {m.metric} = {m.value}{ci} (n {m.n}; base {m.baseline_value}; thr {m.threshold})"
        )


@app.command("etr")
def etr(
    hours_after_peak: Annotated[
        float, typer.Option(help="issue time: hours after the global outage peak")
    ] = 24.0,
    database: Annotated[
        str | None, typer.Option(help="write forecast/snapshot rows to this database")
    ] = None,
    members: Annotated[int | None, typer.Option(help="Monte Carlo members")] = None,
) -> None:
    """Global and regional ETR P10..P90 (90 percent restored) for the Helene story of record."""
    from sgw.models.restoration import artefact, publish

    model, cals, doc = artefact.load()
    items = publish.estimates(publish.story_run(), hours_after_peak, model, cals, members=members)
    for e in items:
        typer.echo(e.model_dump_json())
    if database:
        from sgw.ingest.db import connect, database_url

        with connect(database_url(database)) as conn:
            n = publish.write(conn, items, doc["data_hash"])
        typer.echo(f"wrote {n} forecast rows to {database}")
