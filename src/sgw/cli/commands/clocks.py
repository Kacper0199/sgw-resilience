from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from sgw.cli.support import CliError, guard

app = typer.Typer(
    name="clocks", help="Decision clocks: decide-by, waterfall, critical path, no-regret verdict, event type."
)


def _load(path: Path, advisory: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.is_file():
        raise CliError(f"no member table at {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if advisory not in data.get("advisories", {}):
        raise CliError(f"advisory {advisory!r} not in {path} (have {sorted(data.get('advisories', {}))})")
    return data["advisories"][advisory], data


def _now(adv: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(adv["issued_utc"]).replace("Z", "+00:00"))


def _hm(t: datetime | None) -> str:
    return "-" if t is None else t.strftime("%m-%d %H:%MZ")


@app.command("compute")
@guard
def compute(
    member_table: Annotated[Path, typer.Option("--input", "-i", help="Per-member advisory table (JSON).")],
    advisory: Annotated[str, typer.Option("--advisory", "-a", help="Advisory label, e.g. N or N+1.")] = "N",
    database: Annotated[
        str | None, typer.Option("--database", "-d", help="Store the queue in this database.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print K16 decision cases as JSON.")] = False,
) -> None:
    """Compute the PS-17 chain queue for one advisory (optionally store it)."""
    from sgw.models.clocks.job import run_clock_job
    from sgw.models.clocks.ps17 import ps17_specs

    adv, scenario = _load(member_table, advisory)
    conn = None
    if database:
        from sgw.ingest.db import connect, database_url

        conn = connect(database_url(database))
    try:
        result = run_clock_job(
            ps17_specs(adv, scenario), run_id=f"clocks-{advisory}", conn=conn, now=_now(adv)
        )
    finally:
        if conn is not None:
            conn.close()
    cases = sorted(
        result.cases.values(), key=lambda c: (c.case.effective_decide_by_utc, c.case.decision_case_id)
    )
    if as_json:
        typer.echo(json.dumps([c.case.model_dump(mode="json") for c in cases], indent=1, sort_keys=True))
        return
    typer.echo(f"{'case':32} {'decide-by P10/P50/P90':38} {'effective':12} {'crit':5} {'slack':>6}  verdict")
    for c in cases:
        k = c.case.clock
        rng = f"{_hm(k.decide_by_p10_utc)} {_hm(k.decide_by_utc)[6:]} {_hm(k.decide_by_p90_utc)[6:]}"
        typer.echo(
            f"{c.case.decision_case_id:32} {rng:38} {_hm(c.case.effective_decide_by_utc)[6:]:12} "
            f"{'yes' if c.case.on_critical_path else 'no':5} {c.path.slack_min:6.0f}  "
            f"{c.case.no_regret_verdict.value}"
        )
    for key, reason in sorted(result.no_clock.items()):
        typer.echo(f"no clock: {key}: {reason}")
    if database:
        typer.echo(f"stored {len(cases)} cases in {database}")


@app.command("waterfall")
@guard
def waterfall(
    member_table: Annotated[Path, typer.Option("--input", "-i", help="Per-member advisory table (JSON).")],
    case_id: Annotated[str, typer.Option("--case", "-c", help="Decision case id.")],
    advisory: Annotated[str, typer.Option("--advisory", "-a")] = "N",
) -> None:
    """Print the basis waterfall of one case: every term with its model or rule id."""
    from sgw.models.clocks.ps17 import ps17_specs
    from sgw.models.clocks.service import compute_queue

    adv, scenario = _load(member_table, advisory)
    result = compute_queue(ps17_specs(adv, scenario), now=_now(adv))
    if case_id not in result.cases:
        raise CliError(f"no clocked case {case_id!r}")
    for r in result.cases[case_id].waterfall_rows():
        basis = f"{r.basis.basis_id}@{r.basis.basis_version}" if r.basis else "-"
        if r.unit == "epoch_s":
            vals = " / ".join(_hm(datetime.fromtimestamp(v, tz=UTC)) for v in (r.p10, r.p50, r.p90))
        else:
            vals = f"{r.p10:+.0f} / {r.p50:+.0f} / {r.p90:+.0f} min"
        typer.echo(f"{r.label[:60]:60} {vals:34} {basis}")
    wf = result.cases[case_id].waterfall()
    typer.echo(
        f"decide-by {_hm(wf.decide_by_utc)}; effective {_hm(wf.effective_decide_by_utc)}"
        f" (bound by {wf.bound_by_case_id or 'none'})"
    )


@app.command("event-type")
@guard
def event_type(
    p50: Annotated[float, typer.Option("--p50", help="Predicted peak customers out, P50.")],
    p90: Annotated[float, typer.Option("--p90", help="Predicted peak customers out, P90.")],
    t90_h: Annotated[
        float | None, typer.Option("--t90-h", help="Predicted hours to 90% restored, P50.")
    ] = None,
    storm: Annotated[
        str | None, typer.Option("--storm", help="Scenario storm, excluded from its own analogs.")
    ] = None,
) -> None:
    """Recommend an event type (DC-31) with analog storms; the IC sets it (T2)."""
    from sgw.models.ranking.event_type import recommend

    rec = recommend(
        peak_customers_out_p50=p50, peak_customers_out_p90=p90, t90_h_p50=t90_h, scenario_storm=storm
    )
    typer.echo(
        f"Type {rec.recommended_type} {rec.recommended_name} (driver: {rec.driver}); "
        f"P90 escalation Type {rec.escalation_type}"
    )
    for a in rec.analogs:
        implied = f"Type {a.implied_type}" if a.implied_type is not None else "no implied type"
        typer.echo(f"  analog {a.storm} {a.year}: {a.peak_customers_out:,} out ({a.basis}), {implied}")
