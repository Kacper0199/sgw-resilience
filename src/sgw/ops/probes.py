"""Health probes behind the degraded-mode signals. Each probe is optional and configured by URL, so a test
database or a laptop without the gateway never drifts into M2 on its own.

    SGW_OPS_GATEWAY_URL   llm_gateway base URL (`/healthz`): unreachable or breaker open -> llm_down;
                          breaker half-open or budget past the soft stop -> llm_degraded
    SGW_OPS_OPA_URL       OPA base URL (`/health`): unreachable or non-200 -> opa_down
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from sgw.ops.signals import Probe, Reading

GATEWAY_URL_ENV = "SGW_OPS_GATEWAY_URL"
OPA_URL_ENV = "SGW_OPS_OPA_URL"
TIMEOUT_S = 2.0
OK_BUDGET_LEVELS = frozenset({"ok", "soft_stop_acknowledged"})


def _client() -> httpx.Client:
    """Internal services only: never consult system proxy settings (on macOS that loads a framework that
    is not fork-safe, and a probe must not route through a proxy anyway)."""
    return httpx.Client(trust_env=False)


def _get(client: httpx.Client, url: str) -> tuple[int, Any]:
    response = client.get(url, timeout=TIMEOUT_S)
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


@dataclass
class GatewayProbe:
    base_url: str
    client: httpx.Client = field(default_factory=_client)
    name: str = "gateway"

    def read(self) -> Sequence[Reading]:
        try:
            status, body = _get(self.client, f"{self.base_url.rstrip('/')}/healthz")
        except httpx.HTTPError as exc:
            detail = f"gateway unreachable ({type(exc).__name__})"
            return (Reading("llm_down", True, detail), Reading("llm_degraded", True, detail))
        if status != 200 or not isinstance(body, dict):
            detail = f"gateway /healthz answered {status}"
            return (Reading("llm_down", True, detail), Reading("llm_degraded", True, detail))
        breaker = str((body.get("breaker") or {}).get("state", "unknown"))
        budget = str((body.get("budget") or {}).get("level", "ok"))
        down = breaker == "open"
        degraded = breaker != "closed" or budget not in OK_BUDGET_LEVELS
        return (
            Reading("llm_down", down, f"breaker {breaker}"),
            Reading("llm_degraded", degraded, f"breaker {breaker}, budget {budget}"),
        )


@dataclass
class OpaProbe:
    base_url: str
    client: httpx.Client = field(default_factory=_client)
    name: str = "opa"

    def read(self) -> Sequence[Reading]:
        try:
            status, _ = _get(self.client, f"{self.base_url.rstrip('/')}/health")
        except httpx.HTTPError as exc:
            return (Reading("opa_down", True, f"OPA unreachable ({type(exc).__name__})"),)
        return (Reading("opa_down", status != 200, f"OPA /health answered {status}"),)


def configured_probes(env: Mapping[str, str]) -> list[Probe]:
    probes: list[Probe] = []
    if env.get(GATEWAY_URL_ENV):
        probes.append(GatewayProbe(env[GATEWAY_URL_ENV]))
    if env.get(OPA_URL_ENV):
        probes.append(OpaProbe(env[OPA_URL_ENV]))
    return probes


def read_all(probes: Sequence[Probe]) -> list[Reading]:
    return [reading for probe in probes for reading in probe.read()]
