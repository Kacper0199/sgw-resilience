"""Expected impact in customer-equivalents (CE, PS DC-52, O-05) and the decision-queue order.

    expected_impact = P(loss of service) x (customers + sum of critical-facility weights + equity uplift)
                      x expected duration share
    equity uplift   = residential customers x equity weight x SVI percentile (0..1); weight default 0 (O-05)

A pump station's CE is the connections of the zones it feeds after storage runs out (computed upstream and
passed as `customers`). The queue is ordered by effective decide-by first and expected impact second (DC-52);
`rank_by_impact` is the cross-domain priority order. Policy toggles: equity weight (policy option, requires a
PSC-filed priority policy) and critical weights on/off; both are reported with every breakdown.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sgw.models.ranking.params import critical_weights, equity_weight

MODEL_ID = "ranking.ce"
MODEL_VERSION = "1.0"


@dataclass(frozen=True)
class RankPolicy:
    equity_weight: float = 0.0
    critical_weights_enabled: bool = True

    @classmethod
    def default(cls) -> RankPolicy:
        return cls(equity_weight=equity_weight(), critical_weights_enabled=True)

    def __post_init__(self) -> None:
        if not 0.0 <= self.equity_weight <= 1.0:
            raise ValueError("equity weight must be within [0, 1]")


@dataclass(frozen=True)
class ImpactInput:
    entity_id: str
    p_loss: float
    customers: int
    duration_share: float = 1.0
    critical_facilities: Sequence[str] = ()
    residential_customers: int = 0
    svi_percentile: float | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.p_loss <= 1.0 or not 0.0 <= self.duration_share <= 1.0:
            raise ValueError("p_loss and duration_share must be within [0, 1]")
        if self.customers < 0 or self.residential_customers < 0:
            raise ValueError("customer counts must be non-negative")
        if self.residential_customers > self.customers:
            raise ValueError("residential customers cannot exceed customers")
        if self.svi_percentile is not None and not 0.0 <= self.svi_percentile <= 1.0:
            raise ValueError("SVI percentile must be within [0, 1]")


@dataclass(frozen=True)
class ImpactBreakdown:
    entity_id: str
    p_loss: float
    duration_share: float
    customers_ce: float
    critical_ce: float
    equity_ce: float
    expected_impact: float
    policy: RankPolicy
    critical_detail: dict[str, float] = field(default_factory=dict)
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    @property
    def expected_impact_ce(self) -> int:
        return math.floor(self.expected_impact + 0.5)


def expected_impact(
    item: ImpactInput, policy: RankPolicy, weights: Mapping[str, float] | None = None
) -> ImpactBreakdown:
    table = critical_weights() if weights is None else weights
    detail: dict[str, float] = {}
    if policy.critical_weights_enabled:
        for kind in item.critical_facilities:
            if kind not in table:
                raise KeyError(f"no CE weight for critical facility kind {kind!r}")
            detail[kind] = detail.get(kind, 0.0) + table[kind]
    critical = math.fsum(detail.values())
    equity = (
        item.residential_customers * policy.equity_weight * item.svi_percentile
        if policy.equity_weight > 0 and item.svi_percentile is not None
        else 0.0
    )
    base = math.fsum((float(item.customers), critical, equity))
    return ImpactBreakdown(
        entity_id=item.entity_id,
        p_loss=item.p_loss,
        duration_share=item.duration_share,
        customers_ce=float(item.customers),
        critical_ce=critical,
        equity_ce=equity,
        expected_impact=item.p_loss * base * item.duration_share,
        policy=policy,
        critical_detail=detail,
    )


def rank_by_impact(breakdowns: Sequence[ImpactBreakdown]) -> list[ImpactBreakdown]:
    return sorted(breakdowns, key=lambda b: (-b.expected_impact, b.entity_id))


@dataclass(frozen=True)
class QueueEntry:
    case_id: str
    effective_decide_by_utc: datetime
    impact: ImpactBreakdown


def rank_queue(entries: Sequence[QueueEntry]) -> list[QueueEntry]:
    return sorted(entries, key=lambda e: (e.effective_decide_by_utc, -e.impact.expected_impact, e.case_id))


def rank_changes(before: Sequence[str], after: Sequence[str]) -> dict[str, int]:
    """Positions moved per id (positive = moved up) between two orders of the same ids."""
    pos = {k: i for i, k in enumerate(before)}
    if set(pos) != set(after):
        raise ValueError("both orders must hold the same ids")
    return {k: pos[k] - i for i, k in enumerate(after) if pos[k] != i}
