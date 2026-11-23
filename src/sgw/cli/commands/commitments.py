from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from sgw.cli.support import CliError, guard, repo_root

app = typer.Typer(
    name="commitments",
    help="Commitment watch (approval -> milestones -> drift reopens) and the lead-time learning loop.",
)


def _hm(t: datetime | None) -> str:
    return "-" if t is None else t.strftime("%m-%d %H:%MZ")


@app.command("replay-ps17")
@guard
def replay_ps17(
    database: Annotated[str, typer.Option("--database", "-d", help="Seeded database (`sgw seed`) to use.")],
) -> None:
    """Seed the PS-17 decision (approved through the approval service), replay helene_micro through the
    commitment watch and print the milestones, drift log and the reopened proposal."""
    from sgw.approval.ledger import OutboxSink as ApprovalOutbox
    from sgw.approval.policy import ReferencePolicy
    from sgw.approval.service import ApprovalService
    from sgw.ingest.db import connect, database_url
    from sgw.models.commitments import seed
    from sgw.models.commitments.service import CommitmentWatch, OutboxSink, commitment_id_for, replay

    at: list[datetime] = []

    def clock() -> datetime:
        if not at:
            raise CliError("scenario clock not set")
        return at[-1]

    def set_time(value: datetime) -> None:
        at.append(value)

    approvals = ApprovalService(
        ReferencePolicy(), scenario_clock=clock, token_clock=clock, ledger=ApprovalOutbox()
    )
    with connect(database_url(database)) as conn:
        if conn.execute("SELECT 1 FROM app_user WHERE user_id = 'ic_01'").fetchone() is None:
            raise CliError(f"database {database} has no seeded users; run `uv run sgw seed` against it first")
        seeded = seed.seed_ps17_approved(conn, approvals, set_time)
        events = [e for e in seed.micro_events() if e["event_time"] >= seeded.approved_at.isoformat()[:19]]
        result = replay(conn, CommitmentWatch(approvals, ledger=OutboxSink()), events, set_time=set_time)
        cid = commitment_id_for(seeded.proposal_id, seeded.proposal_version)
        for seq, name, due, met in conn.execute(
            "SELECT seq, name, due_utc, met_utc FROM commitment_milestone"
            " WHERE commitment_id = %s ORDER BY seq",
            (cid,),
        ).fetchall():
            typer.echo(f"milestone {seq} {name:<45} due {_hm(due)}  met {_hm(met)}")
        for row in conn.execute(
            "SELECT detected_at, state, reason, drift_min, tolerance_min, reopened, proposal_version"
            " FROM commitment_drift WHERE commitment_id = %s ORDER BY seq",
            (cid,),
        ).fetchall():
            typer.echo(
                f"drift {_hm(row[0])} state={row[1]} reason={row[2]} drift_min={row[3]}"
                f" tolerance_min={row[4]}"
                f" reopened={row[5]} proposal_version={row[6]}"
            )
        state = conn.execute(
            "SELECT state, proposal_version FROM proposal WHERE proposal_id = %s", (seeded.proposal_id,)
        ).fetchone()
    typer.echo(
        f"proposal {seeded.proposal_id} now {state[0] if state else '?'} v{state[1] if state else '?'}"
    )
    typer.echo(f"created={result.created} reopened={result.reopened} drift_events={len(result.events)}")


def _events(scenario: str) -> tuple[list[dict[str, Any]], str]:
    folder = repo_root() / "data" / "fixtures" / scenario
    if not folder.is_dir():
        raise CliError(f"no fixture folder {folder}")
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("type") == "WorkOrder":
                out.append(row)
    return out, f"fixture:{scenario}"


@app.command("after-action")
@guard
def after_action(
    scenario: Annotated[
        str, typer.Option("--scenario", "-s", help="Fixture folder under data/fixtures.")
    ] = "helene",
    database: Annotated[
        str | None,
        typer.Option("--database", "-d", help="Write the T2 policy-change proposal to this database."),
    ] = None,
    incident: Annotated[
        str, typer.Option("--incident", help="Incident id on the proposal.")
    ] = "INC-HELENE-2024",
    out: Annotated[Path | None, typer.Option("--out", help="Write the evidence table as JSON here.")] = None,
    decision_case: Annotated[
        str | None,
        typer.Option(
            "--decision-case",
            help="Also route the change through the approval service as a T2 policy_change proposal"
            " on this decision case (needs --database).",
        ),
    ] = None,
) -> None:
    """Actual vs assumed lead times (n, median, source) and the proposed values. Never applies them."""
    from dataclasses import asdict

    from sgw.models.commitments import learning
    from sgw.models.commitments.watch import event_time

    events, source = _events(scenario)
    rows = learning.evidence(learning.observe(events), source)
    typer.echo(f"{'lead time':<28}{'assumed':>8}{'n':>4}{'median':>8}{'proposed':>10}  verdict")
    for r in rows:
        median = "-" if r.median_min is None else f"{r.median_min:g}"
        proposed = "-" if r.proposed_min is None else str(r.proposed_min)
        typer.echo(f"{r.key:<28}{r.assumed_min:>8}{r.n:>4}{median:>8}{proposed:>10}  {r.verdict}")
    if out is not None:
        out.write_text(
            json.dumps({"method": learning.method(), "rows": [asdict(r) for r in rows]}, indent=2) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"evidence written to {out}")
    if database:
        from sgw.ingest.db import connect, database_url

        at = max((event_time(e) for e in events), default=None)
        if at is None:
            raise CliError("no work-order events; nothing to propose")
        with connect(database_url(database)) as conn:
            change_id = learning.write_proposal(conn, rows, incident_id=incident, at=at)
            linked = None
            if change_id and decision_case:
                from sgw.approval.ledger import OutboxSink as ApprovalOutbox
                from sgw.approval.policy import ReferencePolicy
                from sgw.approval.service import ApprovalService

                stamp: datetime = at
                approvals = ApprovalService(
                    ReferencePolicy(),
                    scenario_clock=lambda: stamp,
                    token_clock=lambda: stamp,
                    ledger=ApprovalOutbox(),
                )
                linked = learning.route_for_approval(
                    conn, approvals, change_id, decision_case_id=decision_case
                )
        typer.echo(
            f"policy-change proposal {change_id or 'not needed'} (T2, state proposed; values not applied)"
        )
        if linked:
            typer.echo(f"approval proposal {linked} (policy_change, signed by compliance)")
