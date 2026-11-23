"""Crew dispatch policy: the committed data is generated, the Python mirror answers the same
questions as `policy/dispatch.rego` on every persona and assignment case, and the actions offered to each
persona follow from it (read-only personas get none, never disabled buttons)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sgw.approval import testkit
from sgw.contracts.vocab import CrewStatus
from sgw.dispatch import policy, rules
from sgw.dispatch.policy import OpaDispatch, ReferenceDispatch

REF = ReferenceDispatch()
NO_OPA = "no OPA: set SGW_TEST_OPA_URL or start docker"


def person(user_id: str, role: str, function: str, *, can_approve: bool = True) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "roles": [role],
        "functions": [function],
        "can_approve": can_approve,
        "on_shift": True,
    }


ADMIN = person("admin_01", "platform_admin", "platform", can_approve=False)
OPS = person("ops_dm_01", "duty_manager", "operations")
LOG = person("log_01", "logistics_chief", "logistics")
IC = person("ic_01", "incident_commander", "command")
EXEC = person("exec_01", "executive", "executive", can_approve=False)
AUDIT = person("audit_01", "auditor", "audit", can_approve=False)
EVERYONE = (ADMIN, OPS, LOG, IC, EXEC, AUDIT)
PENDING = {"state": "proposed", "proposed_by": "ops_dm_01", "required_function": "logistics"}


def test_committed_dispatch_data_is_generated() -> None:
    assert policy.is_current(), "run `uv run sgw policy-data`"


def test_duty_manager_and_logistics_dispatch_others_read_only() -> None:
    allowed = {s["user_id"] for s in EVERYONE if REF.act({"subject": s}).allow}
    assert allowed == {"ops_dm_01", "log_01"}
    assert REF.act({"subject": EXEC}).deny == ("role_not_allowed",)
    assert REF.act({"subject": ADMIN}).deny == ("role_not_allowed",)


def test_logistics_signs_unless_the_proposer_holds_logistics() -> None:
    assert REF.propose({"subject": OPS}).required_function == "logistics"
    assert REF.propose({"subject": LOG}).required_function == "operations"
    both = {**OPS, "functions": ["operations", "logistics"]}
    verdict = REF.propose({"subject": both})
    assert not verdict.allow and verdict.deny == ("no_signer_function",)


@pytest.mark.parametrize(
    ("subject", "assignment", "deny"),
    [
        (LOG, PENDING, ()),
        (LOG, {**PENDING, "state": "assigned"}, ("not_pending",)),
        (LOG, {**PENDING, "proposed_by": "log_01"}, ("self_sign",)),
        ({**LOG, "can_approve": False}, PENDING, ("not_an_approver",)),
        ({**LOG, "on_shift": False}, PENDING, ("off_shift",)),
        (OPS, {**PENDING, "proposed_by": "admin_01"}, ("function_not_held",)),
        (IC, PENDING, ("function_not_held",)),
        (EXEC, PENDING, ("function_not_held", "not_an_approver")),
    ],
)
def test_sign_rules(subject: dict[str, Any], assignment: dict[str, Any], deny: tuple[str, ...]) -> None:
    verdict = REF.sign({"subject": subject, "assignment": assignment})
    assert verdict.deny == deny and verdict.allow == (deny == ())


def _cases() -> Iterator[tuple[str, dict[str, Any]]]:
    for s in EVERYONE:
        yield "act", {"subject": s}
        yield "propose", {"subject": s}
        for a in (PENDING, {**PENDING, "state": "assigned"}, {**PENDING, "proposed_by": s["user_id"]}):
            yield "sign", {"subject": s, "assignment": a}
    yield "act", {"subject": {}}
    yield "propose", {"subject": {}}
    yield "sign", {"subject": {"user_id": "x"}, "assignment": {}}
    yield "sign", {"subject": {}, "assignment": {"state": "proposed"}}


@pytest.mark.slow
def test_opa_and_reference_agree_on_every_case() -> None:
    with testkit.opa_server() as url:
        if url is None:
            pytest.skip(NO_OPA)  # sgw-allow-skip: CR OPA parity needs docker
        opa = OpaDispatch(url, allow_load=True)
        opa.load()
        try:
            for rule, case in _cases():
                assert getattr(opa, rule)(case) == getattr(REF, rule)(case), (rule, case)
        finally:
            opa.close()


def _state(status: CrewStatus, assignment: str | None = None, kind: str | None = None) -> rules.CrewState:
    return rules.CrewState(
        status=status,
        assignment_state=assignment,
        target_kind=kind,
        proposed_by="ops_dm_01" if assignment else None,
        required_function="logistics" if assignment else None,
    )


def test_read_only_personas_are_offered_nothing() -> None:
    for state in (
        _state(CrewStatus.AVAILABLE),
        _state(CrewStatus.AVAILABLE, "proposed", "decision"),
        _state(CrewStatus.ENROUTE, "assigned", "yard"),
        _state(CrewStatus.BLOCKED),
    ):
        assert rules.actions_for(state, EXEC, REF) == []
        assert rules.actions_for(state, AUDIT, REF) == []


def test_actions_follow_the_crew_state() -> None:
    assert rules.actions_for(_state(CrewStatus.AVAILABLE), OPS, REF) == ["assign", "block"]
    assert rules.actions_for(_state(CrewStatus.AVAILABLE), ADMIN, REF) == []
    pending = _state(CrewStatus.AVAILABLE, "proposed", "decision")
    assert rules.actions_for(pending, LOG, REF) == ["sign", "reject", "withdraw", "block"]
    assert rules.actions_for(pending, OPS, REF) == ["withdraw", "block"]
    assert rules.actions_for(pending, IC, REF) == []
    to_decision = _state(CrewStatus.AVAILABLE, "assigned", "decision")
    assert rules.actions_for(to_decision, OPS, REF) == ["enroute", "onsite", "block", "release"]
    to_yard = _state(CrewStatus.ENROUTE, "assigned", "yard")
    assert rules.actions_for(to_yard, OPS, REF) == ["staged", "block", "release"]
    assert rules.actions_for(_state(CrewStatus.STAGED, "assigned", "yard"), OPS, REF) == ["block", "release"]
    assert rules.actions_for(_state(CrewStatus.BLOCKED, "assigned", "yard"), OPS, REF) == [
        "unblock",
        "release",
    ]
    assert rules.actions_for(_state(CrewStatus.BLOCKED), OPS, REF) == ["unblock"]
