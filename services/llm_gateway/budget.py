from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .policy import PolicyViolation
from .spend import SpendLedger

BUDGET_STATUS = 402


@dataclass(frozen=True)
class Reservation:
    wave: str
    usd: float


@dataclass
class BalanceReading:
    console_balance_usd: float
    ledger_total_at_reading: float


def utc_now() -> datetime:
    return datetime.now(UTC)


class BudgetGuard:
    """Money rules for every live call, checked with all in-flight worst cases held: hard stop (cumulative,
    a user tick raises it), soft stop until acknowledged, balance floor on the console reading (not
    acknowledgeable: with the hard stop it is the 'whichever comes first' pair), the daily cap (today's UTC
    billed rows, resets at UTC midnight) and the per-wave caps."""

    def __init__(
        self, settings: Settings, ledger: SpendLedger, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.clock = clock
        self.ack_usd = settings.budget_ack_usd
        self._lock = threading.Lock()
        self._reservations: dict[int, Reservation] = {}
        self._next_token = 0
        self.reading: BalanceReading | None = (
            BalanceReading(settings.console_balance_usd, ledger.total_usd())
            if settings.console_balance_usd is not None
            else None
        )

    def acknowledge(self, ack_usd: float, console_balance_usd: float | None) -> None:
        self.ack_usd = ack_usd
        if console_balance_usd is not None:
            self.reading = BalanceReading(console_balance_usd, self.ledger.total_usd())

    def estimated_balance(self, total: float) -> float | None:
        if self.reading is None:
            return None
        return round(self.reading.console_balance_usd - (total - self.reading.ledger_total_at_reading), 6)

    def _inflight(self, wave: str | None = None) -> tuple[float, int]:
        items = [r for r in self._reservations.values() if wave is None or r.wave == wave]
        return round(sum(r.usd for r in items), 6), len(items)

    def today_usd(self) -> float:
        return self.ledger.day_usd(self.clock().astimezone(UTC).date())

    def level(self) -> str:
        """Where spend stands against the money rules, for Health and the `x-sgw-budget` header: `ok`,
        `soft_stop_acknowledged`, `soft_stop`, `daily_cap`, `balance_floor` or `hard_stop`."""
        s = self.settings
        with self._lock:
            inflight_usd, _ = self._inflight()
        total = self.ledger.total_usd() + inflight_usd
        acked = self.ack_usd is not None and self.ack_usd >= s.soft_stop_usd
        if total >= s.hard_stop_usd:
            return "hard_stop"
        balance = self.estimated_balance(total)
        if balance is not None and balance <= s.balance_floor_usd:
            return "balance_floor"
        if total >= s.soft_stop_usd and not acked:
            return "soft_stop"
        if s.daily_cap_usd is not None and self.today_usd() + inflight_usd >= s.daily_cap_usd:
            return "daily_cap"
        return "soft_stop_acknowledged" if total >= s.soft_stop_usd else "ok"

    def state(self, wave: str | None = None) -> dict[str, Any]:
        total = self.ledger.total_usd()
        s = self.settings
        inflight_usd, inflight_calls = self._inflight()
        return {
            "level": self.level(),
            "spent_usd": total,
            "inflight_reserved_usd": inflight_usd,
            "inflight_calls": inflight_calls,
            "soft_stop_usd": s.soft_stop_usd,
            "hard_stop_usd": s.hard_stop_usd,
            "ack_usd": self.ack_usd,
            "estimated_balance_usd": self.estimated_balance(total),
            "balance_floor_usd": s.balance_floor_usd,
            "daily_cap_usd": s.daily_cap_usd,
            "today_spent_usd": self.today_usd(),
            "wave": wave,
            "wave_spent_usd": self.ledger.total_usd(wave=wave) if wave else None,
            "wave_calls": self.ledger.live_calls(wave=wave) if wave else None,
            "wave_cap_usd": s.wave_cap_usd,
            "wave_cap_calls": s.wave_cap_calls,
        }

    def reserve(self, *, wave: str, worst_case_usd: float) -> int:
        """Checks every guard with in-flight worst cases counted, then holds this call's worst case."""
        with self._lock:
            self._check(wave=wave, worst_case_usd=worst_case_usd)
            self._next_token += 1
            self._reservations[self._next_token] = Reservation(wave, worst_case_usd)
            return self._next_token

    def release(self, token: int | None) -> None:
        if token is None:
            return
        with self._lock:
            self._reservations.pop(token, None)

    def check_live(self, *, wave: str, worst_case_usd: float) -> None:
        with self._lock:
            self._check(wave=wave, worst_case_usd=worst_case_usd)

    def _check(self, *, wave: str, worst_case_usd: float) -> None:
        s = self.settings
        inflight_usd, _ = self._inflight()
        wave_inflight_usd, wave_inflight_calls = self._inflight(wave)
        booked = self.ledger.total_usd()
        total = booked + inflight_usd
        if total + worst_case_usd >= s.hard_stop_usd:
            raise PolicyViolation(
                "sgw_budget_hard_stop",
                f"spent {booked:.4f} USD + in flight {inflight_usd:.4f}; hard stop {s.hard_stop_usd} USD "
                "needs a user tick",
                BUDGET_STATUS,
            )
        acked = self.ack_usd is not None and self.ack_usd >= s.soft_stop_usd
        if total + worst_case_usd >= s.soft_stop_usd and not acked:
            raise PolicyViolation(
                "sgw_budget_soft_stop",
                f"spent {booked:.4f} USD (+{inflight_usd:.4f} in flight) reaches soft stop "
                f"{s.soft_stop_usd}; maintainer must set LLM_BUDGET_ACK",
                BUDGET_STATUS,
            )
        balance = self.estimated_balance(total + worst_case_usd)
        if balance is not None and balance <= s.balance_floor_usd:
            raise PolicyViolation(
                "sgw_balance_floor",
                f"estimated console balance {balance:.2f} USD <= floor {s.balance_floor_usd}",
                BUDGET_STATUS,
            )
        if s.daily_cap_usd is not None:
            today = self.today_usd()
            if round(today + inflight_usd + worst_case_usd, 6) > s.daily_cap_usd:
                raise PolicyViolation(
                    "sgw_daily_cap",
                    f"today (UTC) {today:.4f} USD + in flight {inflight_usd:.4f} + this call "
                    f"{worst_case_usd:.4f} exceeds the daily cap {s.daily_cap_usd} USD",
                    BUDGET_STATUS,
                )
        calls = self.ledger.live_calls(wave=wave) + wave_inflight_calls
        if s.wave_cap_calls is not None and calls >= s.wave_cap_calls:
            raise PolicyViolation(
                "sgw_wave_cap_calls", f"wave {wave} reached {s.wave_cap_calls} live calls", BUDGET_STATUS
            )
        wave_total = self.ledger.total_usd(wave=wave) + wave_inflight_usd
        if s.wave_cap_usd is not None and wave_total + worst_case_usd > s.wave_cap_usd:
            raise PolicyViolation(
                "sgw_wave_cap_usd", f"wave {wave} would exceed {s.wave_cap_usd} USD", BUDGET_STATUS
            )
