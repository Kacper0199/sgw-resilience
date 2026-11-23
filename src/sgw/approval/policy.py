"""Policy decision point for approvals (DC-36, package `sgw.approval`).

`OpaPolicy` asks the OPA server; `ReferencePolicy` is the S8 fallback with the same input and output
contract, kept in lock-step with the Rego by a parity test over the same cases. Both fail closed: an
unreachable or undefined decision raises `PolicyUnavailableError`, which the API maps to 503.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from sgw.approval import policy_data
from sgw.approval.errors import PolicyUnavailableError

PolicyInput = dict[str, Any]


class PolicyNotLoadedError(PolicyUnavailableError):
    code = "POLICY_NOT_LOADED"


@dataclass(frozen=True)
class Classification:
    tier: str
    base_tier: str
    required_functions: tuple[str, ...]
    escalators: tuple[str, ...]
    policy_version: str


@dataclass(frozen=True)
class ProposeDecision:
    allow: bool
    deny: tuple[str, ...]
    classification: Classification


@dataclass(frozen=True)
class ApproveDecision:
    allow: bool
    deny: tuple[str, ...]
    complete: bool
    remaining_functions: tuple[str, ...] = field(default_factory=tuple)


class PolicyEngine(Protocol):
    def propose(self, payload: PolicyInput) -> ProposeDecision: ...

    def approve(self, payload: PolicyInput) -> ApproveDecision: ...


def _classification(raw: Mapping[str, Any]) -> Classification:
    return Classification(
        tier=str(raw["tier"]),
        base_tier=str(raw["base_tier"]),
        required_functions=tuple(raw["required_functions"]),
        escalators=tuple(raw["escalators"]),
        policy_version=str(raw["policy_version"]),
    )


def parse_propose(raw: Any) -> ProposeDecision:
    try:
        return ProposeDecision(
            allow=raw["allow"] is True,
            deny=tuple(raw["deny"]),
            classification=_classification(raw["classification"]),
        )
    except (KeyError, TypeError) as error:
        raise PolicyUnavailableError(f"malformed propose decision: {error}") from error


def parse_approve(raw: Any) -> ApproveDecision:
    try:
        return ApproveDecision(
            allow=raw["allow"] is True,
            deny=tuple(raw["deny"]),
            complete=raw["complete"] is True,
            remaining_functions=tuple(raw["remaining_functions"]),
        )
    except (KeyError, TypeError) as error:
        raise PolicyUnavailableError(f"malformed approve decision: {error}") from error


OPA_TOKEN_ENV = "SGW_OPA_TOKEN"  # noqa: S105
OPA_DEV_LOAD_ENV = "SGW_OPA_DEV_LOAD"


def opa_auth_headers() -> dict[str, str]:
    """Bearer token for the stack's OPA (`--authentication=token`); none when unset (ad hoc test servers)."""
    token = os.environ.get(OPA_TOKEN_ENV)
    return {"Authorization": f"Bearer {token}"} if token else {}


def runtime_load_allowed(allow_load: bool) -> bool:
    return allow_load or os.environ.get(OPA_DEV_LOAD_ENV) == "1"


class OpaPolicy:
    """Client of an OPA server. The stack's OPA serves `policy/` read-only from files and refuses writes;
    `load()` (pushing the Rego and tier data over REST) is only for ad hoc test servers: it refuses unless
    the client was built with `allow_load=True` or SGW_OPA_DEV_LOAD=1."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 2.0,
        client: httpx.Client | None = None,
        reload_on_missing: bool = False,
        allow_load: bool = False,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_s, headers=opa_auth_headers()
        )
        self._reload_on_missing = reload_on_missing
        self._allow_load = allow_load

    def close(self) -> None:
        self._client.close()

    def load(self) -> None:
        if not runtime_load_allowed(self._allow_load):
            raise PolicyUnavailableError(
                "runtime policy load is disabled: OPA serves policy/ read-only from files "
                f"(test servers: allow_load=True or {OPA_DEV_LOAD_ENV}=1)"
            )
        try:
            rego = policy_data.REGO_PATH.read_text(encoding="utf-8")
            r1 = self._client.put(
                f"/v1/data/{policy_data.DATA_DOCUMENT}",
                content=json.dumps(policy_data.build()),
                headers={"Content-Type": "application/json"},
            )
            r1.raise_for_status()
            r2 = self._client.put(
                f"/v1/policies/{policy_data.POLICY_ID}", content=rego, headers={"Content-Type": "text/plain"}
            )
            r2.raise_for_status()
        except httpx.HTTPError as error:
            raise PolicyUnavailableError(f"cannot load the approval policy into OPA: {error}") from error

    def _query(self, rule: str, payload: PolicyInput) -> Any:
        """A missing decision (OPA restarted without the policy) triggers one re-load and one retry when
        `reload_on_missing` is set; otherwise, or if it is still missing, fail closed."""
        try:
            return self._query_once(rule, payload)
        except PolicyNotLoadedError:
            if not self._reload_on_missing:
                raise
        self.load()
        return self._query_once(rule, payload)

    def _query_once(self, rule: str, payload: PolicyInput) -> Any:
        try:
            response = self._client.post(f"/v1/data/sgw/approval/{rule}", json={"input": payload})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PolicyUnavailableError(f"OPA query {rule} failed: {error}") from error
        if "result" not in body:
            raise PolicyNotLoadedError(f"OPA returned no decision for {rule} (policy not loaded?)")
        return body["result"]

    def propose(self, payload: PolicyInput) -> ProposeDecision:
        return parse_propose(self._query("propose", payload))

    def approve(self, payload: PolicyInput) -> ApproveDecision:
        return parse_approve(self._query("approve", payload))


class ReferencePolicy:
    """Python mirror of `policy/approval.rego` over the same `data.sgw.tiers` document."""

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = dict(data) if data is not None else policy_data.build()

    def classify(self, payload: PolicyInput) -> Classification:
        rules: Mapping[str, Any] = self.data["rules"]
        esc_cfg: Mapping[str, Any] = self.data["escalation"]
        proposal = payload.get("proposal", {})
        facts = payload.get("facts", {})
        context = payload.get("context", {})
        rule = rules.get(proposal.get("action_type"))
        base = rule["tier"] if rule else "T4"
        escalators: set[str] = set()
        customers = facts.get("customers_affected")
        if _is_number(customers) and customers >= esc_cfg["customer_limit"]:
            escalators.add("customers_ge_limit")
        if len(proposal.get("target_ids", [])) > esc_cfg["target_limit"]:
            escalators.add("targets_gt_limit")
        escalators.update(flag for flag in esc_cfg["flags"] if facts.get(flag) is True)
        mode = context.get("degraded_mode")
        if isinstance(mode, str) and mode != esc_cfg["normal_degraded_mode"]:
            escalators.add("degraded_mode")
        escalated = base == "T2" and bool(escalators)
        if escalated and rule:
            functions = tuple(rule["escalated_functions"])
        elif rule:
            functions = tuple(rule["approver_functions"])
        else:
            functions = ()
        return Classification(
            tier="T3" if escalated else base,
            base_tier=base,
            required_functions=functions,
            escalators=tuple(sorted(escalators)),
            policy_version=str(self.data["policy_version"]),
        )

    def propose(self, payload: PolicyInput) -> ProposeDecision:
        c = self.classify(payload)
        proposal = payload.get("proposal", {})
        rule = self.data["rules"].get(proposal.get("action_type"))
        deny: set[str] = set()
        if not rule:
            deny.add("unknown_action_type")
        if c.tier == "T4":
            deny.add("tier_t4_prohibited")
        if rule:
            proposers = rule["proposers"]
            allowed = proposal.get("proposed_by") in proposers or (
                proposal.get("initiator_kind") == "agent" and "agent" in proposers
            )
            if not allowed:
                deny.add("proposer_not_allowed")
        if proposal.get("initiator_kind") == "person" and proposal.get("proposed_by") != payload.get(
            "subject", {}
        ).get("user_id"):
            deny.add("proposer_is_not_subject")
        return ProposeDecision(allow=not deny, deny=tuple(sorted(deny)), classification=c)

    def approve(self, payload: PolicyInput) -> ApproveDecision:
        subject = payload.get("subject", {})
        proposal = payload.get("proposal", {})
        context = payload.get("context", {})
        approval = payload.get("approval", {})
        approvals: Sequence[Mapping[str, Any]] = payload.get("approvals", [])
        required = list(proposal.get("required_functions", []))
        function = approval.get("function")
        user = subject.get("user_id")
        deny: set[str] = set()
        if approval.get("decision") not in ("approve", "reject"):
            deny.add("bad_decision")
        if proposal.get("state") not in self.data["reviewable_states"]:
            deny.add("not_reviewable")
        if proposal.get("tier") not in self.data["approval_tiers"]:
            deny.add("no_approval_tier")
        if proposal.get("tier") == "T3" and len(set(required)) != 2:
            deny.add("t3_needs_two_functions")
        expires = proposal.get("expires_at_ns")
        if _is_number(expires) and context.get("now_ns", 0) >= expires:
            deny.add("expired")
        if user == proposal.get("proposed_by"):
            deny.add("self_approval")
        if user == proposal.get("requested_by"):
            deny.add("initiator_approval")
        if subject.get("can_approve") is not True:
            deny.add("not_an_approver")
        if subject.get("on_shift") is False:
            deny.add("off_shift")
        if function not in subject.get("functions", []):
            deny.add("function_not_held")
        if function not in required:
            deny.add("function_not_required")
        if any(a.get("function") == function for a in approvals):
            deny.add("function_already_signed")
        if any(a.get("approver_id") == user for a in approvals):
            deny.add("approver_already_signed")
        age = approval.get("evidence_oldest_age_s")
        limit = self.data["evidence_age_limit_s"].get(proposal.get("tier"))
        if _is_number(age) and limit is not None and age > limit:
            deny.add("evidence_too_old")
        approving = approval.get("decision") == "approve"
        signed = {a["function"] for a in approvals if a.get("decision") == "approve"}
        signers = {a["approver_id"] for a in approvals if a.get("decision") == "approve"}
        if approving:
            signed.add(function)
            signers.add(user)
        remaining = sorted({f for f in required if f not in signed})
        complete = (
            approving
            and not deny
            and not remaining
            and len(signers) >= len(set(required))
            and proposal.get("proposed_by") not in signers
            and proposal.get("requested_by") not in signers
        )
        return ApproveDecision(
            allow=not deny, deny=tuple(sorted(deny)), complete=complete, remaining_functions=tuple(remaining)
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)
