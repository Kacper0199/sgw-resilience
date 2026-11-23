"""Policy decision point for break-glass, co-sign and envelopes (packages `sgw.breakglass`, `sgw.envelope`).

The Rego files hold rules only; their data `data.sgw.governance` is generated here from PLAN section 2 and
the K10 policy numbers (`policy_break_glass_cosign_hours`) and committed at `DATA_PATH`. `OpaGovernance`
asks OPA, `ReferenceGovernance` is the S8 Python mirror over the same document; both fail closed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from sgw.approval import envelope as env_mod
from sgw.approval.errors import PolicyUnavailableError
from sgw.approval.policy import PolicyNotLoadedError, opa_auth_headers, runtime_load_allowed
from sgw.approval.policy_data import POLICY_DIR
from sgw.common import numbers
from sgw.contracts import approval as ap
from sgw.contracts.approval import EnvelopeBound
from sgw.contracts.vocab import ApprovalFunction, Tier

DATA_PATH = POLICY_DIR / "sgw" / "governance" / "data.json"
DATA_DOCUMENT = "sgw/governance"
REGO_FILES = {"sgw-breakglass": POLICY_DIR / "breakglass.rego", "sgw-envelope": POLICY_DIR / "envelope.rego"}
BREAK_GLASS_TIERS = (Tier.T3.value,)
OPEN_STATES = ("proposed", "in_review", "escalated")
COSIGN_STATES = ("approved", "executed")
REASON_MIN_CHARS = 10

PolicyInput = dict[str, Any]


def cosign_hours() -> int:
    hours = int(numbers.value("policy_break_glass_cosign_hours"))
    if hours != ap.BREAK_GLASS_COSIGN_HOURS:
        raise ValueError("numbers.yaml and K8 disagree on the break-glass co-sign window")
    return hours


def build() -> dict[str, Any]:
    return {
        "generated_from": "PLAN section 2 (break-glass row, envelope rule) and data/numbers/numbers.yaml",
        "break_glass": {
            "tiers": list(BREAK_GLASS_TIERS),
            "eligible_function": ApprovalFunction.COMMAND.value,
            "open_states": list(OPEN_STATES),
            "cosign_states": list(COSIGN_STATES),
            "reason_min_chars": REASON_MIN_CHARS,
            "cosign_hours": cosign_hours(),
        },
        "envelope": {
            "inside_tier": Tier.T1.value,
            "outside_tier": Tier.T3.value,
            "pct": env_mod.envelope_pct(),
        },
    }


def render() -> str:
    return json.dumps(build(), indent=2, sort_keys=True) + "\n"


def write() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(render(), encoding="utf-8", newline="\n")


def is_current() -> bool:
    return DATA_PATH.is_file() and DATA_PATH.read_text(encoding="utf-8") == render()


@dataclass(frozen=True)
class BreakGlassDecision:
    allow: bool
    deny: tuple[str, ...]


@dataclass(frozen=True)
class CosignDecision:
    allow: bool
    deny: tuple[str, ...]
    function: str | None


class GovernancePolicy(Protocol):
    def break_glass(self, payload: PolicyInput) -> BreakGlassDecision: ...

    def cosign(self, payload: PolicyInput) -> CosignDecision: ...

    def envelope(self, payload: PolicyInput) -> env_mod.EnvelopeAssessment: ...


def _parse_break_glass(raw: Any) -> BreakGlassDecision:
    try:
        return BreakGlassDecision(allow=raw["allow"] is True, deny=tuple(raw["deny"]))
    except (KeyError, TypeError) as error:
        raise PolicyUnavailableError(f"malformed break-glass decision: {error}") from error


def _parse_cosign(raw: Any) -> CosignDecision:
    try:
        fn = raw["function"]
        return CosignDecision(allow=raw["allow"] is True, deny=tuple(raw["deny"]), function=fn or None)
    except (KeyError, TypeError) as error:
        raise PolicyUnavailableError(f"malformed co-sign decision: {error}") from error


def _parse_envelope(raw: Any) -> env_mod.EnvelopeAssessment:
    try:
        return env_mod.parse_assessment(raw)
    except (KeyError, TypeError, ValueError) as error:
        raise PolicyUnavailableError(f"malformed envelope decision: {error}") from error


class OpaGovernance:
    """Client of the OPA server; `load()` pushes both Rego files and the generated data document."""

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
                "(test servers: allow_load=True or SGW_OPA_DEV_LOAD=1)"
            )
        try:
            self._client.put(
                f"/v1/data/{DATA_DOCUMENT}",
                content=json.dumps(build()),
                headers={"Content-Type": "application/json"},
            ).raise_for_status()
            for policy_id, path in REGO_FILES.items():
                self._client.put(
                    f"/v1/policies/{policy_id}",
                    content=path.read_text(encoding="utf-8"),
                    headers={"Content-Type": "text/plain"},
                ).raise_for_status()
        except httpx.HTTPError as error:
            raise PolicyUnavailableError(f"cannot load the governance policy into OPA: {error}") from error

    def _query(self, path: str, payload: PolicyInput) -> Any:
        """A missing decision (OPA started without these files) re-loads once when allowed; else 503."""
        try:
            return self._query_once(path, payload)
        except PolicyNotLoadedError:
            if not self._reload_on_missing:
                raise
        self.load()
        return self._query_once(path, payload)

    def _query_once(self, path: str, payload: PolicyInput) -> Any:
        try:
            response = self._client.post(f"/v1/data/{path}", json={"input": payload})
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PolicyUnavailableError(f"OPA query {path} failed: {error}") from error
        if "result" not in body:
            raise PolicyNotLoadedError(f"OPA returned no decision for {path} (policy not loaded?)")
        return body["result"]

    def break_glass(self, payload: PolicyInput) -> BreakGlassDecision:
        return _parse_break_glass(self._query("sgw/breakglass/break_glass", payload))

    def cosign(self, payload: PolicyInput) -> CosignDecision:
        return _parse_cosign(self._query("sgw/breakglass/cosign", payload))

    def envelope(self, payload: PolicyInput) -> env_mod.EnvelopeAssessment:
        return _parse_envelope(self._query("sgw/envelope/assessment", payload))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


class ReferenceGovernance:
    """Python mirror of `policy/breakglass.rego` and `policy/envelope.rego` over `data.sgw.governance`."""

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self.data = dict(data) if data is not None else build()

    def break_glass(self, payload: PolicyInput) -> BreakGlassDecision:
        cfg = self.data["break_glass"]
        subject = payload.get("subject", {})
        proposal = payload.get("proposal", {})
        bg = payload.get("break_glass", {})
        context = payload.get("context", {})
        reason = bg.get("reason")
        deny: set[str] = set()
        if proposal.get("tier") not in cfg["tiers"]:
            deny.add("not_break_glass_tier")
        if not isinstance(reason, str) or len(reason.strip()) < cfg["reason_min_chars"]:
            deny.add("reason_too_short")
        if subject.get("break_glass_eligible") is not True:
            deny.add("not_eligible")
        if cfg["eligible_function"] not in subject.get("functions", []):
            deny.add("function_not_held")
        if subject.get("on_shift") is False:
            deny.add("off_shift")
        if proposal.get("state") not in cfg["open_states"]:
            deny.add("not_open")
        expires = proposal.get("expires_at_ns")
        if _is_number(expires) and context.get("now_ns", 0) >= expires:
            deny.add("expired")
        if bg.get("existing") is True:
            deny.add("already_used")
        if subject.get("user_id") is not None and subject.get("user_id") == proposal.get("proposed_by"):
            deny.add("ic_is_proposer")
        return BreakGlassDecision(allow=not deny, deny=tuple(sorted(deny)))

    def cosign(self, payload: PolicyInput) -> CosignDecision:
        cfg = self.data["break_glass"]
        subject = payload.get("subject", {})
        proposal = payload.get("proposal", {})
        bg = payload.get("break_glass", {})
        user = subject.get("user_id")
        held = subject.get("functions", [])
        second = sorted(
            f for f in proposal.get("required_functions", []) if f != cfg["eligible_function"] and f in held
        )
        deny: set[str] = set()
        if subject.get("can_approve") is not True:
            deny.add("not_an_approver")
        if subject.get("on_shift") is False:
            deny.add("off_shift")
        if user == bg.get("ic_id"):
            deny.add("cosigner_is_ic")
        if user == proposal.get("proposed_by"):
            deny.add("cosigner_is_proposer")
        if not second:
            deny.add("no_second_function")
        if bg.get("cosigned") is True:
            deny.add("already_cosigned")
        if proposal.get("state") not in cfg["cosign_states"]:
            deny.add("not_cosignable")
        return CosignDecision(
            allow=not deny, deny=tuple(sorted(deny)), function=second[0] if second else None
        )

    def envelope(self, payload: PolicyInput) -> env_mod.EnvelopeAssessment:
        env = payload.get("envelope", {})
        bounds = {k: EnvelopeBound(**v) for k, v in env.get("bounds", {}).items()}
        params = payload.get("params", {})
        now_ns = int(payload.get("context", {}).get("now_ns", 0))
        until_ns = int(env.get("valid_until_ns", 0))
        return env_mod.assess_bounds(bounds, params, expired=now_ns > until_ns)
