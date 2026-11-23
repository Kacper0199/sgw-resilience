"""Consequence time from typed model outputs, with every term of the basis waterfall carrying its id (O-03).

The consequence of a decision is an anchor event (e.g. the first time a member's P(PS-17 power loss) reaches
the material threshold) plus additive durations (e.g. zone tank drain to the state floor). Uncertainty is
propagated per ensemble member: each member's terms are summed first, then P10/P50/P90 (linear interpolation)
are taken over the member totals. When a term is monotone in the anchor (the PS-17 drain is), this agrees with
summing per-term quantiles up to interpolation; when terms are anti-correlated it does not (tested). Members
that never reach the anchor do not vote; with fewer than `min_member_share` of members reaching it, there is
no clock.

Waterfall rows decompose real members: at each quantile the nearest-rank member of the totals is shown term by
term (its terms sum exactly), with each term's own P10-P90 across members as context. The difference between
the interpolated quantile and that member's total is one `ensemble_nonadditivity` row per quantile, a
bookkeeping term the UI greys out and never presents as a driver.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import numpy as np

from sgw.contracts.clocks import ClockBasis

QUANTILES = (10.0, 50.0, 90.0)
DEFAULT_MIN_MEMBER_SHARE = 1.0 / 3.0


class InsufficientMembers(ValueError):
    pass


@dataclass(frozen=True)
class AddOnTerm:
    """A duration added to the anchor; `minutes` is one value per member, or a single constant."""

    label: str
    basis: ClockBasis
    minutes: Sequence[float | None] | float

    def per_member(self, n: int) -> list[float | None]:
        if isinstance(self.minutes, int | float):
            return [float(self.minutes)] * n
        if len(self.minutes) != n:
            raise ValueError(f"term {self.label!r} has {len(self.minutes)} values for {n} members")
        return [None if m is None else float(m) for m in self.minutes]


@dataclass(frozen=True)
class ConsequenceSpec:
    consequence_basis: ClockBasis
    anchor_label: str
    anchor_basis: ClockBasis
    anchor_utc: Sequence[datetime | None]
    terms: Sequence[AddOnTerm] = ()
    min_member_share: float = DEFAULT_MIN_MEMBER_SHARE


class TermKind(StrEnum):
    ANCHOR = "anchor"
    TERM = "term"
    ENSEMBLE_NONADDITIVITY = "ensemble_nonadditivity"
    LEAD_TIME = "lead_time"
    CRITICAL_PATH = "critical_path"


@dataclass(frozen=True)
class WaterfallRow:
    label: str
    basis: ClockBasis | None
    p10: float
    p50: float
    p90: float
    unit: str = "min"
    term_kind: TermKind = TermKind.TERM
    context_p10: float | None = None
    context_p90: float | None = None


@dataclass(frozen=True)
class ConsequenceEstimate:
    p10_utc: datetime
    p50_utc: datetime
    p90_utc: datetime
    basis: ClockBasis
    members_used: int
    members_total: int
    rows: tuple[WaterfallRow, ...] = field(default_factory=tuple)

    @property
    def member_share(self) -> float:
        return self.members_used / self.members_total


def _epoch(t: datetime) -> float:
    if t.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return t.timestamp()


def to_minute(seconds: float) -> datetime:
    """Floor to the minute: a deadline is never rounded later, and a whole-minute shift of every input shifts
    the clock by exactly that much (banker's rounding would not)."""
    return datetime.fromtimestamp(math.floor(seconds / 60.0) * 60.0, tz=UTC)


def nearest_rank(q: float, n: int) -> int:
    """0-based index of the nearest-rank q-th percentile of n sorted values."""
    return max(1, math.ceil(q / 100.0 * n)) - 1


def _q(values: Sequence[float]) -> tuple[float, float, float]:
    a, b, c = (float(v) for v in np.percentile(np.asarray(values, dtype=float), QUANTILES))
    return a, b, c


def estimate(spec: ConsequenceSpec) -> ConsequenceEstimate:
    n = len(spec.anchor_utc)
    if n == 0:
        raise InsufficientMembers("no ensemble members")
    columns = [t.per_member(n) for t in spec.terms]
    used: list[int] = []
    for i, anchor in enumerate(spec.anchor_utc):
        if anchor is not None and all(col[i] is not None for col in columns):
            used.append(i)
    if len(used) == 0 or len(used) < spec.min_member_share * n:
        raise InsufficientMembers(
            f"{len(used)} of {n} members reach {spec.anchor_label!r}; need {spec.min_member_share:.2f}"
        )
    anchors = [_epoch(spec.anchor_utc[i]) for i in used]  # type: ignore[arg-type]
    term_minutes = [[float(col[i]) for i in used] for col in columns]  # type: ignore[arg-type]
    totals = [a + 60.0 * math.fsum(tm[k] for tm in term_minutes) for k, a in enumerate(anchors)]
    clock = tuple(to_minute(x) for x in _q(totals))
    t10, t50, t90 = clock
    order = sorted(range(len(totals)), key=lambda k: (totals[k], k))
    picks = [order[nearest_rank(q, len(order))] for q in QUANTILES]
    rows = [
        WaterfallRow(
            spec.anchor_label,
            spec.anchor_basis,
            anchors[picks[0]],
            anchors[picks[1]],
            anchors[picks[2]],
            unit="epoch_s",
            term_kind=TermKind.ANCHOR,
            context_p10=_q(anchors)[0],
            context_p90=_q(anchors)[2],
        )
    ]
    for term, tm in zip(spec.terms, term_minutes, strict=True):
        ctx = _q(tm)
        rows.append(
            WaterfallRow(
                term.label,
                term.basis,
                tm[picks[0]],
                tm[picks[1]],
                tm[picks[2]],
                context_p10=ctx[0],
                context_p90=ctx[2],
            )
        )
    residual = [(t.timestamp() - totals[k]) / 60.0 for t, k in zip(clock, picks, strict=True)]
    if any(abs(r) > 1e-9 for r in residual):
        rows.append(
            WaterfallRow(
                "ensemble non-additivity (quantile minus the shown member)",
                None,
                residual[0],
                residual[1],
                residual[2],
                term_kind=TermKind.ENSEMBLE_NONADDITIVITY,
            )
        )
    return ConsequenceEstimate(
        p10_utc=t10,
        p50_utc=t50,
        p90_utc=t90,
        basis=spec.consequence_basis,
        members_used=len(used),
        members_total=n,
        rows=tuple(rows),
    )


def minutes_between(a: datetime, b: datetime) -> float:
    return (b - a) / timedelta(minutes=1)
