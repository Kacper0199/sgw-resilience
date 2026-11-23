"""Policy decision point for crew dispatch (package `sgw.dispatch`).

`policy/dispatch.rego` holds the rules; its data `data.sgw.crew_dispatch` is generated here and committed at
`DATA_PATH`. `OpaDispatch` asks OPA, `ReferenceDispatch` is the Python mirror over the same document, kept in
lock-step by a parity test. Both fail closed: an unreachable or undefined decision raises
`PolicyUnavailableError` (503).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from sgw.approval.errors import PolicyUnavailableError
from sgw.approval.policy import PolicyNotLoadedError, opa_auth_headers, runtime_load_allowed
from sgw.approval.policy_data import POLICY_DIR
from sgw.contracts.vocab import ApprovalFunction

DATA_PATH = POLICY_DIR / "sgw" / "crew_dispatch" / "data.json"
DATA_DOCUMENT = "sgw/crew_dispatch"
REGO_PATH = POLICY_DIR / "dispatch.rego"
POLICY_ID = "sgw-dispatch"
POLICY_VERSION = "dispatch-2026.11.21-r29"
ACTOR_ROLES: tuple[str, ...] = ("duty_manager", "logistics_chief")
SIGNER_FUNCTIONS: tuple[ApprovalFunction, ...] = (ApprovalFunction.LOGISTICS, ApprovalFunction.OPERATIONS)
OPEN_STATES: tuple[str, ...] = ("proposed",)

PolicyInput = dict[str, Any]


def build() -> dict[str, Any]:
    return {
        "generated_from": "sgw.dispatch.policy (D-100 Q-03 C: crew dispatch with one sign-off)",
        "policy_version": POLICY_VERSION,
        "actor_roles": list(ACTOR_ROLES),
        "signer_functions": [f.value for f in SIGNER_FUNCTIONS],
        "open_states": list(OPEN_STATES),
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def write() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(render(), encoding="utf-8", newline="\n")


def is_current() -> bool:
    return DATA_PATH.is_file() and DATA_PATH.read_text(encoding="utf-8") == render()


@dataclass(frozen=True)
class Verdict:
    allow: bool
    deny: tuple[str, ...]


@dataclass(frozen=True)
class ProposeVerdict:
    allow: bool
    deny: tuple[str, ...]
    required_function: str | None
    policy_version: str


class DispatchPolicy(Protocol):
    def act(self, payload: PolicyInput) -> Verdict: ...

    def propose(self, payload: PolicyInput) -> ProposeVerdict: ...

    def sign(self, payload: PolicyInput) -> Verdict: ...


def _verdict(raw: Any) -> Verdict:
    try:
        return Verdict(allow=raw["allow"] is True, deny=tuple(raw["deny"]))
    except (KeyError, TypeError) as error:
        raise PolicyUnavailableError(f"malformed dispatch decision: {error}") from error


def _propose_verdict(raw: Any) -> ProposeVerdict:
    try:
        required = raw["required_function"]
        return ProposeVerdict(
            allow=raw["allow"] is True,
            deny=tuple(raw["deny"]),
            required_function=str(required) if required is not None else None,
            policy_version=str(raw["policy_version"]),
        )
    except (KeyError, TypeError) as error:
        raise PolicyUnavailableError(f"malformed dispatch decision: {error}") from error


class OpaDispatch:
    """Client of the OPA server. The stack's OPA serves `policy/` read-only from files; `load()` is only for
    ad hoc test servers (allow_load=True or SGW_OPA_DEV_LOAD=1)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 2.0,
        client: httpx.Client | None = None,
        allow_load: bool = False,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_s, headers=opa_auth_headers()
        )
        self._allow_load = allow_load

    def close(self) -> None:
        self._client.close()

    def load(self) -> None:
        if not runtime_load_allowed(self._allow_load):
            raise PolicyUnavailableError("runtime policy load is disabled: OPA serves policy/ from files")
        try:
            self._client.put(
                f"/v1/data/{DATA_DOCUMENT}",
                content=json.dumps(build()),
                headers={"Content-Type": "application/json"},
            ).raise_for_status()
            self._client.put(
                f"/v1/policies/{POLICY_ID}",
                content=REGO_PATH.read_text(encoding="utf-8"),
                headers={"Content-Type": "text/plain"},
            ).raise_for_status()
        except httpx.HTTPError as error:
            raise PolicyUnavailableError(f"cannot load the dispatch policy into OPA: {error}") from error

    def _query(self, rule: str, payload: PolicyInput) -> Any:
        try:
            response = self._client.post(f"/v1/data/sgw/dispatch/{rule}", json={"input": payload})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PolicyUnavailableError(f"OPA query dispatch/{rule} failed: {error}") from error
        if "result" not in body:
            raise PolicyNotLoadedError(f"OPA returned no decision for dispatch/{rule} (policy not loaded?)")
        return body["result"]

    def act(self, payload: PolicyInput) -> Verdict:
        return _verdict(self._query("act", payload))

    def propose(self, payload: PolicyInput) -> ProposeVerdict:
        return _propose_verdict(self._query("propose", payload))

    def sign(self, payload: PolicyInput) -> Verdict:
        return _verdict(self._query("sign", payload))


class ReferenceDispatch:
    """Python mirror of `policy/dispatch.rego` over the same `data.sgw.crew_dispatch` document; it also shows
    each persona only the actions it may take."""

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = dict(data) if data is not None else build()

    def _act_deny(self, subject: Mapping[str, Any]) -> set[str]:
        roles = subject.get("roles") or []
        return set() if any(r in self.data["actor_roles"] for r in roles) else {"role_not_allowed"}

    def act(self, payload: PolicyInput) -> Verdict:
        deny = self._act_deny(payload.get("subject", {}))
        return Verdict(allow=not deny, deny=tuple(sorted(deny)))

    def propose(self, payload: PolicyInput) -> ProposeVerdict:
        subject = payload.get("subject", {})
        held = subject.get("functions") or []
        candidates = [f for f in self.data["signer_functions"] if f not in held]
        required = candidates[0] if candidates else None
        deny = self._act_deny(subject)
        if required is None:
            deny.add("no_signer_function")
        return ProposeVerdict(
            allow=not deny,
            deny=tuple(sorted(deny)),
            required_function=required,
            policy_version=str(self.data["policy_version"]),
        )

    def sign(self, payload: PolicyInput) -> Verdict:
        subject = payload.get("subject", {})
        assignment = payload.get("assignment", {})
        deny: set[str] = set()
        if assignment.get("state") not in self.data["open_states"]:
            deny.add("not_pending")
        user = subject.get("user_id")
        if user is not None and user == assignment.get("proposed_by"):
            deny.add("self_sign")
        if subject.get("can_approve") is not True:
            deny.add("not_an_approver")
        if subject.get("on_shift") is False:
            deny.add("off_shift")
        if assignment.get("required_function") not in (subject.get("functions") or []):
            deny.add("function_not_held")
        return Verdict(allow=not deny, deny=tuple(sorted(deny)))
