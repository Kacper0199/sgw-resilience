from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="optimise",
    help="A5 crew pre-positioning: two-stage SAA MILP (HiGHS), courses of action, VSS/EVPI, envelope.",
)

SCENARIO = Annotated[str, typer.Option(help="replay scenario")]
ADVISORY = Annotated[str, typer.Option(help="advisory label, e.g. N or N+1")]
DATABASE = Annotated[str, typer.Option(help="database name (your own, e.g. sgw_wp16)")]
REPORT_PATH = Path("evals/reports/saa.json")


def _print_summary(doc: dict[str, object]) -> None:
    plans = doc["plans"]
    assert isinstance(plans, list)
    typer.echo(f"{doc['scenario']} advisory {doc['advisory']} size {doc['size']} caps {doc['caps_groups']}")
    for p in plans:
        oos = p["out_of_sample"]
        solver = p["solver"]
        typer.echo(
            f"{p['plan_id']:6} MA groups {p['early_mutual_aid_groups']:4}"
            f"  USD/day {p['committed_early_mutual_aid_usd_per_day']:>11,}"
            f"  E[USD] {p['expected_cost']['total_mutual_aid_usd']:>12,}"
            f"  E[CH] {oos['expected_customer_hours']:>12,}  P90 {oos['p90_customer_hours']:>12,}"
            f"  idle MA {oos['expected_idle_early_mutual_aid_persons']:>7}"
            f"  truth {p['synthetic_truth_customer_hours']:>12,}"
            f"  stress {p['observed_scale_stress_customer_hours']:>12,}"
            f"  {solver['seconds']}s gap {solver['mip_gap']:.2e}"
        )
    typer.echo(f"VSS {json.dumps(doc['vss'])}")
    typer.echo(f"EVPI {json.dumps(doc['evpi'])}")
    typer.echo(f"SAA bounds {json.dumps(doc['saa_bounds'])}")
    typer.echo(f"CVaR check {json.dumps(doc['cvar_check'])}")
    typer.echo(f"Band {json.dumps(doc['planning_band_check'])}")


@app.command("plan")
def plan(
    scenario: SCENARIO = "helene",
    advisory: ADVISORY = "N",
    out: Annotated[Path | None, typer.Option(help="write the plan document (JSON) here")] = None,
) -> None:
    """Solve the courses of action and baselines for one advisory and print the summary (no database)."""
    from sgw.models.optimise.coa import run
    from sgw.models.optimise.plan import document
    from sgw.models.optimise.scenarios import build_context

    t0 = time.perf_counter()
    doc = document(run(build_context(scenario, advisory)))
    _print_summary(doc)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}")
    typer.echo(f"total {time.perf_counter() - t0:.1f}s")


@app.command("report")
def report(
    scenario: SCENARIO = "helene",
    advisory: ADVISORY = "N",
    path: Annotated[Path, typer.Option(help="K17 report path")] = REPORT_PATH,
) -> None:
    """Write the K17 report `evals/reports/saa.json` (solve time, gap, VSS, EVPI, per-COA outcomes)."""
    from sgw.models.optimise import report as report_mod
    from sgw.models.optimise.coa import run
    from sgw.models.optimise.plan import document
    from sgw.models.optimise.scenarios import build_context

    pr = run(build_context(scenario, advisory))
    _print_summary(document(pr))
    rep = report_mod.build(pr)
    report_mod.write(rep, path)
    failed = [m.metric for m in rep.metrics if not m.passed]
    typer.echo(f"wrote {path}: {len(rep.metrics)} rows, {len(failed)} not passed: {failed}")


@app.command("enqueue")
def enqueue(database: DATABASE, scenario: SCENARIO = "helene", advisory: ADVISORY = "N") -> None:
    """Queue an SAA job (returns at once with the job id)."""
    from sgw.ingest.db import connect, database_url
    from sgw.models.optimise.job import enqueue as enqueue_job

    with connect(database_url(database)) as conn:
        typer.echo(enqueue_job(conn, scenario=scenario, advisory=advisory, requested_by="cli"))


@app.command("work")
def work(
    database: DATABASE,
    drain: Annotated[bool, typer.Option(help="keep claiming until the queue is empty")] = False,
) -> None:
    """Claim and run queued SAA jobs; each stores a `crew_plan` snapshot."""
    from sgw.ingest.db import connect, database_url
    from sgw.models.optimise.job import work_one

    with connect(database_url(database)) as conn:
        while True:
            res = work_one(conn)
            if res is None:
                typer.echo("queue empty")
                return
            typer.echo(f"job {res.job_id} -> snapshot {res.snapshot_id} in {res.seconds:.1f}s")
            if not drain:
                return


@app.command("status")
def status(database: DATABASE, job_id: str) -> None:
    """Show the state of one SAA job."""
    from sgw.ingest.db import connect, database_url
    from sgw.models.optimise.job import status as job_status

    with connect(database_url(database)) as conn:
        found = job_status(conn, job_id)
    if found is None:
        typer.echo(f"no SAA job {job_id}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(found))
