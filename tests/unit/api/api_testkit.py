from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sgw.api.ledger import ControlSnapshot, LedgerRow
from sgw.contracts.vocab import Classification, RunMode


@dataclass
class FakeSource:
    rows: dict[int, LedgerRow] = field(default_factory=dict)
    control_snap: ControlSnapshot | None = None
    fetches: int = 0

    async def head(self) -> int:
        return max(self.rows, default=0)

    async def fetch_after(self, after: int, upto: int, limit: int) -> list[LedgerRow]:
        self.fetches += 1
        keys = sorted(k for k in self.rows if after < k <= upto)[:limit]
        return [self.rows[k] for k in keys]

    async def control(self) -> ControlSnapshot | None:
        return self.control_snap

    async def existing(self, seqs: list[int]) -> list[int]:
        return sorted(k for k in self.rows if k in set(seqs))

    def add(
        self, seq: int, event_type: str = "OutageEvent", payload: dict[str, object] | None = None
    ) -> None:
        self.rows[seq] = make_row(seq, event_type, payload)


def make_row(
    seq: int, event_type: str = "OutageEvent", payload: dict[str, object] | None = None
) -> LedgerRow:
    return LedgerRow(
        ledger_seq=seq,
        event_id=f"00000000-0000-4000-8000-{seq:012d}",
        event_type=event_type,
        event_time=datetime(2024, 9, 26, tzinfo=UTC) + timedelta(minutes=seq),
        run_mode=RunMode.REPLAY,
        classification=Classification.C1,
        payload=payload or {"n": seq},
    )


class FakeMonotonic:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


REPO_ROOT = Path(__file__).resolve().parents[3]
USERS_YAML = REPO_ROOT / "data" / "seed" / "users.yaml"
