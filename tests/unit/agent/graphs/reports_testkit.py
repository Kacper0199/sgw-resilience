from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sgw.agent.graphs import after_action, etr, sitrep
from sgw.agent.nodes.llm import GatewayClient, GatewayTags
from sgw.agent.nodes.ports import InMemoryProposalPort, ProposalPort
from sgw.agent.nodes.run_task import RunTask
from sgw.contracts.vocab import RunMode
from sgw.models.restoration.publish import EtrEstimate
from sgw.reports import sources
from sgw.reports.after_action import (
    AfterActionReview,
    BreakGlassUse,
    ChainCheck,
    ClockResult,
    TimelineEntry,
)
from sgw.reports.nodes import ReportDeps

DATA = Path(__file__).resolve().parent / "data"
REPO = Path(__file__).resolve().parents[4]
ESTIMATES = DATA / "etr_story_h24.jsonl"
GRAPHS = {"etr": etr.build, "sitrep": sitrep.build, "after_action": after_action.build}
USERS = {
    "etr": ("plan_etr_01", "planning"),
    "sitrep": ("ops_dm_01", "operations"),
    "after_action": ("audit_01", "audit"),
}
REVIEW_AT = datetime(2024, 10, 5, 12, 0, tzinfo=UTC)


def estimates() -> list[EtrEstimate]:
    return sources.load_estimates(ESTIMATES)


def clock(case: str, title: str, step: str, due: str, outcome: str, **kw: Any) -> ClockResult:
    return ClockResult(
        decision_case_id=case,
        step=step,
        title=title,
        effective_decide_by=datetime.fromisoformat(due),
        decided_at=kw.get("decided_at"),
        decided_by=kw.get("decided_by"),
        proposal_id=kw.get("proposal_id"),
        outcome=outcome,  # type: ignore[arg-type]
        margin_min=kw.get("margin_min"),
    )


OPEN_CLOCK = clock(
    "DC-D3-PS17-POWER",
    "Feeder or generator priority for the hospital-zone pump station PS-17",
    "D3",
    "2024-09-28T20:00:00+00:00",
    "open",
)


def fixed_review(at: datetime = REVIEW_AT) -> AfterActionReview:
    """A review as the audit chain would give it: one clock met by approval, one missed after break-glass,
    one break-glass co-signed late."""
    met = clock(
        "DC-D2-CREWS-AIK",
        "Pre-position crews at Sandhill and Millpond yards before tropical-storm winds",
        "D2",
        "2024-09-26T09:20:00+00:00",
        "met",
        decided_at=datetime(2024, 9, 26, 8, 40, tzinfo=UTC),
        decided_by="approval",
        proposal_id="PRP-CREW-AIK-0926A",
        margin_min=40,
    )
    missed = clock(
        "DC-D3-PS17-POWER",
        "Feeder or generator priority for the hospital-zone pump station PS-17",
        "D3",
        "2024-09-27T03:29:00+00:00",
        "missed",
        decided_at=datetime(2024, 9, 27, 4, 5, tzinfo=UTC),
        decided_by="break_glass",
        proposal_id="PRP-PS17-0927A",
        margin_min=-36,
    )
    bg = BreakGlassUse(
        break_glass_id=1,
        proposal_id="PRP-PS17-0927A",
        ic_id="ic_01",
        tier="T3",
        reason="Pressure floor at the hospital connection at risk and water operations unreachable",
        used_at=datetime(2024, 9, 27, 4, 5, tzinfo=UTC),
        cosign_due=datetime(2024, 9, 28, 4, 5, tzinfo=UTC),
        cosigned_by="wtr_lead_01",
        cosigned_at=datetime(2024, 9, 28, 6, 0, tzinfo=UTC),
        status="cosigned_late",
        table_agrees=True,
    )
    return AfterActionReview(
        as_of=at,
        chain=ChainCheck(
            ok=True, checked_to_seq=42, first_bad_seq=None, signed_head_seq=42, trusted_to_seq=42, problems=[]
        ),
        clocks=[met, missed],
        break_glass=[bg],
        timeline=[
            TimelineEntry(
                seq=7,
                occurred_at=bg.used_at,
                kind="break_glass_used",
                actor_id="ic_01",
                subject=bg.proposal_id,
            )
        ],
    )


def deps(llm: Any, port: ProposalPort | None = None, **kw: Any) -> ReportDeps:
    base: dict[str, Any] = {
        "estimates": estimates,
        "open_clocks": lambda _at: [OPEN_CLOCK],
        "cosign_open": lambda: 0,
        "review": fixed_review,
    }
    base |= kw
    return ReportDeps(llm=llm, proposals=port or InMemoryProposalPort(), **base)


def run_task(
    graph_id: str,
    llm: Any,
    *,
    port: ProposalPort | None = None,
    run_input: dict[str, Any] | None = None,
    run_id: str | None = None,
    **kw: Any,
) -> RunTask:
    if graph_id == "after_action":
        kw.setdefault("as_of", REVIEW_AT)
    user, role = USERS[graph_id]
    return RunTask(
        run_id=run_id or f"run-{graph_id}-test",
        thread_id="thr-test",
        graph_id=graph_id,
        graph=GRAPHS[graph_id](),
        deps=deps(llm, port, **kw),
        user_id=user,
        user_role=role,
        run_mode=RunMode.REPLAY,
        run_input=run_input or {},
    )


def gateway_client(url: str) -> GatewayClient:
    return GatewayClient(url, tags=GatewayTags(purpose="test", wave="W5"))
