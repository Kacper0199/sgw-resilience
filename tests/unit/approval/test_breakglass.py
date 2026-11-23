"""Break-glass (PLAN section 2): IC alone, mandatory reason, co-sign task due in 24 h by the second function,
after-action flag; policy and the 4750 database triggers each refuse on their own."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pydantic
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from sgw.approval import audit, errors
from sgw.approval import testkit as tk
from sgw.approval.breakglass import COSIGN_JOB_KIND, BreakGlassService
from sgw.approval.breakglass_policy import BreakGlassDecision, CosignDecision, ReferenceGovernance
from sgw.approval.envelope import EnvelopeAssessment, EnvelopeService
from sgw.approval.ledger import MemorySink
from sgw.approval.service import ApprovalService
from sgw.approval.signer import AuditPaths, Ed25519Signer, Keyring
from sgw.contracts.api_models import BreakGlassRequest, CosignTaskOut, ProposalCard, StaleProposal
from sgw.contracts.events import BreakGlassUsed, DecisionApproved

EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
REASON = "Feeder lockout imminent and the logistics chief is unreachable"


class PermissiveGovernance:
    """Allows everything, so the database triggers are the only check left."""

    def break_glass(self, payload: dict[str, Any]) -> BreakGlassDecision:
        return BreakGlassDecision(allow=True, deny=())

    def cosign(self, payload: dict[str, Any]) -> CosignDecision:
        return CosignDecision(allow=True, deny=(), function="logistics")

    def envelope(self, payload: dict[str, Any]) -> EnvelopeAssessment:
        raise NotImplementedError


@pytest.fixture
def sink() -> MemorySink:
    return MemorySink()


@pytest.fixture
def approvals(clock: tk.MutableClock, token_clock: tk.MutableClock, sink: MemorySink) -> ApprovalService:
    from sgw.approval.policy import ReferencePolicy

    return ApprovalService(ReferencePolicy(), scenario_clock=clock, token_clock=token_clock, ledger=sink)


@pytest.fixture(scope="module")
def signer() -> Ed25519Signer:
    return Ed25519Signer.generate()


@pytest.fixture(scope="module")
def audit_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("audit")


@pytest.fixture(scope="module")
def anchors(audit_dir: Path) -> audit.AnchorStore:
    return audit.AnchorStore(audit_dir / "anchors")


@pytest.fixture(scope="module")
def paths(audit_dir: Path, signer: Ed25519Signer) -> AuditPaths:
    found = AuditPaths(
        keyring=audit_dir / "keyring.json", key_dir=audit_dir / "keys", anchors=audit_dir / "anchors"
    )
    Keyring().rotate(signer, EPOCH).save(found.keyring)
    return found


@pytest.fixture
def bgs(
    approvals: ApprovalService, clock: tk.MutableClock, signer: Ed25519Signer, anchors: audit.AnchorStore
) -> BreakGlassService:
    policy = ReferenceGovernance()
    return BreakGlassService(
        approvals,
        policy,
        envelopes=EnvelopeService(policy, clock=clock, ledger=approvals.ledger),
        signer=lambda: (signer, anchors),
    )


def _req(card: ProposalCard, reason: str = REASON) -> BreakGlassRequest:
    return BreakGlassRequest(
        proposal_version=card.proposal_version, action_hash=card.action_hash, reason=reason
    )


def _as_fixture(conn: psycopg.Connection[Any], sql: str, *args: Any) -> None:
    """Fixture set-up past the 4800 proposal guard (triggers off for this transaction only)."""
    with conn.transaction():
        conn.execute("SET LOCAL session_replication_role = replica")
        conn.execute(sql, args)


def _count(conn: psycopg.Connection[Any], sql: str, *args: Any) -> int:
    row = conn.execute(sql, args).fetchone()
    assert row is not None
    return int(row[0])


def test_ic_alone_with_reason_approves_opens_cosign_task_and_flags(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService, sink: MemorySink
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    out = bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    after = out.value
    assert after.state == "approved" and after.break_glass is not None
    bg = after.break_glass
    assert bg.ic_id == "ic_01" and bg.flagged_for_after_action and bg.cosigned_by is None
    assert bg.cosign_due_utc - bg.used_at_utc == timedelta(hours=24)
    tasks = bgs.tasks(conn)
    mine = [t for t in tasks if t.proposal_id == card.proposal_id]
    assert len(mine) == 1 and mine[0].functions == ("logistics",) and not mine[0].overdue
    assert (
        _count(
            conn,
            "SELECT count(*) FROM job WHERE kind = %s AND state = 'queued' AND payload->>'proposal_id' = %s",
            COSIGN_JOB_KIND,
            card.proposal_id,
        )
        == 1
    )
    assert after.envelope is not None and set(after.envelope.bounds) == set(card.params)
    types = [type(e).__name__ for e in out.events]
    assert types == ["BreakGlassUsed", "DecisionApproved"]
    approved = next(e for e in out.events if isinstance(e, DecisionApproved))
    assert approved.break_glass and approved.approver_ids == ["ic_01"]
    queued = {e.type for e in sink.queued if getattr(e.payload, "proposal_id", None) == card.proposal_id}
    assert {"BreakGlassUsed", "DecisionApproved", "EnvelopeApproved"} <= queued
    assert all(
        isinstance(e.payload, BreakGlassUsed) is False or e.payload.reason == REASON for e in sink.queued
    )
    assert sink.drain_states and sink.drain_states[-1] == (True, "IDLE")
    kinds = [
        r[0]
        for r in conn.execute(
            "SELECT kind FROM audit_event WHERE subject = %s ORDER BY seq", (card.proposal_id,)
        ).fetchall()
    ]
    assert kinds == ["proposal_created", "execution_token_issued", "envelope_approved", "break_glass_used"]
    token = tk.repo_token(conn, card.proposal_id)
    assert token is not None and token["proposal_version"] == card.proposal_version
    effect = approvals.burn(
        conn,
        token_id=token["token_id"],
        proposal_id=card.proposal_id,
        proposal_version=card.proposal_version,
        action_hash=card.action_hash,
    )
    assert effect == f"EFF-{card.proposal_id}"


def test_break_glass_is_notarised_by_a_signed_checkpoint(
    conn: psycopg.Connection[Any],
    approvals: ApprovalService,
    bgs: BreakGlassService,
    signer: Ed25519Signer,
    anchors: audit.AnchorStore,
    clock: tk.MutableClock,
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    head = conn.execute("SELECT max(seq) FROM audit_event WHERE stream = 'global'").fetchone()
    signed = conn.execute("SELECT max(seq) FROM audit_checkpoint WHERE stream = 'global'").fetchone()
    assert head is not None and signed is not None and head[0] == signed[0]
    ring = Keyring().rotate(signer, EPOCH)
    report = audit.verify(conn, keyring=ring, anchors=anchors)
    assert report.ok, report.problems
    assert report.result().notary == "signed"


def test_reason_is_mandatory(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    with pytest.raises(pydantic.ValidationError):
        BreakGlassRequest(proposal_version=1, action_hash=card.action_hash, reason="")
    with pytest.raises(errors.UnprocessableError) as caught:
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card, "   urgent!    "))
    assert caught.value.code == "REASON_REQUIRED"
    assert _count(conn, "SELECT count(*) FROM break_glass WHERE proposal_id = %s", card.proposal_id) == 0
    assert approvals.card(conn, card.proposal_id).state == "proposed"


@pytest.mark.parametrize("user", ["ops_dm_02", "log_01", "exec_01"])
def test_only_the_ic_may_break_glass(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService, user: str
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    with pytest.raises(errors.ForbiddenError) as caught:
        bgs.invoke(conn, user_id=user, proposal_id=card.proposal_id, request=_req(card))
    assert "not_eligible" in caught.value.details["deny"]


def test_stale_version_gets_the_k3_stale_body(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    bad = BreakGlassRequest(proposal_version=card.proposal_version, action_hash="0" * 64, reason=REASON)
    with pytest.raises(errors.PreconditionFailedError) as caught:
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=bad)
    assert isinstance(caught.value.stale, StaleProposal)
    with pytest.raises(errors.PreconditionFailedError):
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card), if_match='"9-x"')


def test_second_use_and_closed_proposals_conflict(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    with pytest.raises(errors.ConflictError) as caught:
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    assert caught.value.code in {"PROPOSAL_NOT_OPEN", "BREAK_GLASS_USED"}


def test_break_glass_is_for_t3_only(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = approvals.create(conn, proposed_by="ops_dm_01", request=tk.staging_request()).value
    assert card.tier == "T2"
    with pytest.raises(errors.ForbiddenError) as caught:
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    assert "not_break_glass_tier" in caught.value.details["deny"]


def test_expired_proposal_cannot_be_broken_open(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService, clock: tk.MutableClock
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    clock.advance(minutes=61)
    with pytest.raises(errors.ConflictError) as caught:
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    assert caught.value.code == "PROPOSAL_EXPIRED"


@pytest.mark.parametrize(
    ("user", "tier_t2", "message"),
    [("log_01", False, "not break-glass eligible"), ("ic_01", True, "T3 only")],
)
def test_database_refuses_on_its_own(
    conn: psycopg.Connection[Any],
    approvals: ApprovalService,
    clock: tk.MutableClock,
    user: str,
    tier_t2: bool,
    message: str,
) -> None:
    open_svc = BreakGlassService(approvals, PermissiveGovernance())
    if tier_t2:
        card = approvals.create(conn, proposed_by="ops_dm_01", request=tk.staging_request()).value
    else:
        card = tk.new_crew_proposal(conn, approvals)
    with pytest.raises(errors.ForbiddenError) as caught:
        open_svc.invoke(conn, user_id=user, proposal_id=card.proposal_id, request=_req(card))
    assert caught.value.code == "DB_AUTHORITY_DENIED" and message in caught.value.message
    assert approvals.card(conn, card.proposal_id).state != "approved"


@pytest.mark.parametrize("case", ["expired", "ic_is_proposer"])
def test_database_refuses_expired_or_own_proposals(
    conn: psycopg.Connection[Any], approvals: ApprovalService, clock: tk.MutableClock, case: str
) -> None:
    open_svc = BreakGlassService(approvals, PermissiveGovernance())
    card = tk.new_crew_proposal(conn, approvals)
    if case == "expired":
        clock.advance(minutes=61)
    else:
        _as_fixture(
            conn, "UPDATE proposal SET proposed_by = 'ic_01' WHERE proposal_id = %s", card.proposal_id
        )
    with pytest.raises(errors.ForbiddenError) as caught:
        open_svc.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    assert caught.value.code == "DB_AUTHORITY_DENIED"
    assert ("expired" if case == "expired" else "own proposal") in caught.value.message


def test_ic_cannot_break_glass_own_proposal_by_policy(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    _as_fixture(conn, "UPDATE proposal SET proposed_by = 'ic_01' WHERE proposal_id = %s", card.proposal_id)
    with pytest.raises(errors.ForbiddenError) as caught:
        bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    assert "ic_is_proposer" in caught.value.details["deny"]


def test_token_needs_approvals_or_a_break_glass_row(
    conn: psycopg.Connection[Any], approvals: ApprovalService
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    _as_fixture(conn, "UPDATE proposal SET state = 'approved' WHERE proposal_id = %s", card.proposal_id)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO execution_token (proposal_id, proposal_version, action_hash, expires_at)"
            " VALUES (%s, %s, %s, now() + interval '1 minute')",
            (card.proposal_id, card.proposal_version, card.action_hash),
        )


def test_break_glass_rows_are_evidence(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = tk.new_crew_proposal(conn, approvals)
    bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    for stmt in (
        "DELETE FROM break_glass WHERE proposal_id = %s",
        "UPDATE break_glass SET reason = 'rewritten afterwards' WHERE proposal_id = %s",
        "UPDATE break_glass SET flagged = false WHERE proposal_id = %s",
        "DELETE FROM envelope WHERE proposal_id = %s",
        "UPDATE envelope SET bounds = '{}' WHERE proposal_id = %s",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(stmt, (card.proposal_id,))


# ---- co-sign --------------------------------------------------------------------------------------------


def _broken_open(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> ProposalCard:
    card = tk.new_crew_proposal(conn, approvals)
    return bgs.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card)).value


def test_second_function_cosigns_once_and_closes_the_task(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = _broken_open(conn, approvals, bgs)
    out = bgs.cosign(conn, user_id="log_01", proposal_id=card.proposal_id)
    assert out.value.cosigned_by == "log_01" and not out.value.overdue
    assert out.events[0].decision == "cosign" and out.events[0].function == "logistics"  # type: ignore[attr-defined]
    assert approvals.card(conn, card.proposal_id).break_glass.cosigned_by == "log_01"  # type: ignore[union-attr]
    assert (
        _count(
            conn,
            "SELECT count(*) FROM job WHERE kind = %s AND state = 'done' AND payload->>'proposal_id' = %s",
            COSIGN_JOB_KIND,
            card.proposal_id,
        )
        == 1
    )
    assert card.proposal_id not in {t.proposal_id for t in bgs.tasks(conn)}
    with pytest.raises(errors.ConflictError):
        bgs.cosign(conn, user_id="log_01", proposal_id=card.proposal_id)


@pytest.mark.parametrize(
    ("user", "deny"),
    [
        ("ic_01", "cosigner_is_ic"),
        ("ops_dm_01", "cosigner_is_proposer"),
        ("wtr_comp_01", "no_second_function"),
    ],
)
def test_cosign_refusals(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService, user: str, deny: str
) -> None:
    card = _broken_open(conn, approvals, bgs)
    with pytest.raises(errors.ForbiddenError) as caught:
        bgs.cosign(conn, user_id=user, proposal_id=card.proposal_id)
    assert deny in caught.value.details["deny"]


def test_database_refuses_a_cosign_by_the_proposer(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService
) -> None:
    card = _broken_open(conn, approvals, bgs)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "UPDATE break_glass SET cosigned_by = 'ops_dm_01', cosigned_at = used_at WHERE proposal_id = %s",
            (card.proposal_id,),
        )


def test_overdue_is_flagged_once_and_a_late_cosign_stays_flagged(
    conn: psycopg.Connection[Any], approvals: ApprovalService, bgs: BreakGlassService, clock: tk.MutableClock
) -> None:
    card = _broken_open(conn, approvals, bgs)
    clock.advance(hours=25)
    first = bgs.flag_overdue(conn)
    assert any(t.proposal_id == card.proposal_id and t.overdue for t in bgs.tasks(conn))
    assert first and bgs.flag_overdue(conn) == []
    late = bgs.cosign(conn, user_id="log_01", proposal_id=card.proposal_id)
    assert late.value.overdue and late.events[0].reason_code == "late_cosign"  # type: ignore[attr-defined]
    assert approvals.card(conn, card.proposal_id).break_glass.flagged_for_after_action  # type: ignore[union-attr]


# ---- HTTP -----------------------------------------------------------------------------------------------


def test_http_break_glass_round_trip(
    db_url: str, approvals: ApprovalService, bgs: BreakGlassService, paths: AuditPaths
) -> None:
    from psycopg_pool import ConnectionPool

    from sgw.api.routers.audit import router
    from sgw.approval.breakglass_deps import SESSION_CSRF, SESSION_STEP_UP
    from sgw.approval.deps import SESSION_READER

    app = FastAPI()
    app.include_router(router)
    app.state.breakglass_service = bgs
    app.state.approval_service = approvals
    app.state.audit_paths = paths

    def header_user(x_test_user: str | None = Header(default=None)) -> str:
        if not x_test_user:
            raise HTTPException(status_code=401, detail="no session")
        return x_test_user

    for dep in (SESSION_STEP_UP, SESSION_CSRF, SESSION_READER):
        app.dependency_overrides[dep] = header_user
    with (
        ConnectionPool(db_url, min_size=1, max_size=3, kwargs={"autocommit": True}, open=True) as pool,
        psycopg.connect(db_url, autocommit=True) as conn,
    ):
        app.state.approval_db_pool = pool
        card = tk.new_crew_proposal(conn, approvals)
        with TestClient(app) as client:
            body = _req(card).model_dump(mode="json")
            url = f"/api/proposals/{card.proposal_id}/break-glass"
            assert client.post(url, json=body).status_code == 401
            short = client.post(url, json={**body, "reason": "too short"}, headers={"X-Test-User": "ic_01"})
            assert short.status_code == 422
            denied = client.post(url, json=body, headers={"X-Test-User": "ops_dm_02"})
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "POLICY_DENIED"
            ok = client.post(
                url, json=body, headers={"X-Test-User": "ic_01", "If-Match": f'"1-{card.action_hash}"'}
            )
            assert ok.status_code == 200, ok.text
            got = ProposalCard.model_validate(ok.json())
            assert got.state == "approved" and got.break_glass is not None
            assert ok.headers["ETag"] == f'"1-{card.action_hash}"'
            again = client.post(url, json=body, headers={"X-Test-User": "ic_01"})
            assert again.status_code == 409
            page = client.get("/api/audit", params={"from_seq": "1"}, headers={"X-Test-User": "audit_01"})
            assert page.status_code == 200 and page.json()[0]["seq"] == 1
            bad = client.get("/api/audit", params={"from_seq": "x"}, headers={"X-Test-User": "audit_01"})
            assert bad.status_code == 422
            verified = client.post("/api/audit/verify", headers={"X-Test-User": "audit_01"})
            assert verified.status_code == 200 and verified.json()["ok"] is True
            limited = client.post("/api/audit/verify", headers={"X-Test-User": "audit_01"})
            assert limited.status_code == 429 and int(limited.headers["Retry-After"]) >= 1
            cached = client.post("/api/audit/verify", headers={"X-Test-User": "ic_01"})
            assert cached.status_code == 200 and cached.json() == verified.json()
            cos = f"/api/proposals/{card.proposal_id}/cosign"
            assert client.post(cos, headers={"X-Test-User": "ops_dm_02"}).status_code == 403
            stale = client.post(cos, headers={"X-Test-User": "log_01", "If-Match": '"9-x"'})
            assert stale.status_code == 412
            done = client.post(cos, headers={"X-Test-User": "log_01", "If-Match": f'"1-{card.action_hash}"'})
            assert done.status_code == 200, done.text
            task = CosignTaskOut.model_validate(done.json())
            assert task.cosigned_by == "log_01" and task.functions == ["logistics"] and not task.overdue
            assert client.post(cos, headers={"X-Test-User": "log_01"}).status_code == 409
            assert (
                client.post("/api/proposals/PRP-NONE/cosign", headers={"X-Test-User": "log_01"}).status_code
                == 404
            )


def test_envelope_failure_does_not_undo_break_glass_and_is_audited(
    conn: psycopg.Connection[Any], approvals: ApprovalService, clock: tk.MutableClock
) -> None:
    class FailingEnvelopes(EnvelopeService):
        def record(self, conn: psycopg.Connection[Any], proposal_id: str, *, actor_id: str) -> Any:
            conn.execute(
                "INSERT INTO envelope (envelope_id, proposal_id, bounds, valid_until)"
                " VALUES ('X', %s, '{}', now())",
                (proposal_id,),
            )

    svc = BreakGlassService(approvals, ReferenceGovernance(), envelopes=FailingEnvelopes(clock=clock))
    card = tk.new_crew_proposal(conn, approvals)
    out = svc.invoke(conn, user_id="ic_01", proposal_id=card.proposal_id, request=_req(card))
    assert out.value.state == "approved" and out.value.envelope is None
    kinds = [
        r[0]
        for r in conn.execute(
            "SELECT kind FROM audit_event WHERE subject = %s ORDER BY seq", (card.proposal_id,)
        ).fetchall()
    ]
    assert "envelope_failed" in kinds and kinds[-1] == "break_glass_used"
