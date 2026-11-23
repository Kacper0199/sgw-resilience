"""Capability gate in front of every LLM node. A closed gate (kill level or degraded mode removes
`llm_calls`, or the control state is unreadable) and the gateway's typed refusal (`sgw_llm_disabled`, 503)
both surface as `LlmUnavailable("llm_disabled")`, which the text nodes answer with their M2 template from the
same slot values. The model is never called while the gate is closed."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from sgw.agent.nodes.llm import LlmClient, LlmRequest, LlmResponse, LlmUnavailable
from sgw.contracts.vocab import DegradedMode, KillLevel
from sgw.ops.gate import LLM_DISABLED_CODE, LlmGate, llm_gate

LLM_DISABLED = "llm_disabled"
GateCheck = Callable[[], LlmGate]


def db_gate(connect: Callable[[], psycopg.Connection[Any]]) -> GateCheck:
    """A gate check that reads the platform state on its own connection; any database error closes it."""

    def check() -> LlmGate:
        try:
            with connect() as conn:
                return llm_gate(conn)
        except psycopg.Error as exc:
            return LlmGate(
                False, f"control state unreadable: {type(exc).__name__}", KillLevel.K0, DegradedMode.M0
            )

    return check


@dataclass
class GatedLlmClient:
    inner: LlmClient
    gate: GateCheck

    async def create(self, request: LlmRequest) -> LlmResponse:
        decision = self.gate()
        if not decision.allowed:
            raise LlmUnavailable(LLM_DISABLED, decision.reason)
        try:
            return await self.inner.create(request)
        except LlmUnavailable as exc:
            if exc.reason == "gateway_503" and exc.detail == LLM_DISABLED_CODE:
                raise LlmUnavailable(LLM_DISABLED, LLM_DISABLED_CODE) from exc
            raise


def gated(client: LlmClient, gate: GateCheck | None) -> LlmClient:
    return client if gate is None else GatedLlmClient(client, gate)
