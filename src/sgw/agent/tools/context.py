"""What an executor may see: the server-injected context (time, role, region, ceiling), the read models and
the worker's evidence ledger. Model-written arguments never carry any of these (K5 `FORBIDDEN_MODEL_ARGS`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sgw.agent.tools.outcome import EvidenceLedger
from sgw.agent.tools.reads import ReadPort
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction


@dataclass
class ToolContext:
    injected: InjectedContext
    reads: ReadPort
    ledger: EvidenceLedger = field(default_factory=EvidenceLedger)

    @property
    def at(self) -> datetime:
        return self.injected.as_of

    @property
    def role(self) -> ApprovalFunction:
        return self.injected.user_role
