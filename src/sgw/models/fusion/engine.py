"""A3 asset-loss nowcast: root-aware log-odds evidence fusion (OSR ADR 1.3-1.8, DC-16).

Inside a root, supporting and opposing signals are combined strongest-first with the marginal effective
sample size `c_k = n_eff(k) - n_eff(k-1)`, `n_eff(k, rho) = k / (1 + (k - 1) rho)`; the root value is clamped
to `[-cap, +cap]`; roots add. Flat mode adds every root to the logit of the prior. Split mode keeps hazard and
asset-condition evidence apart, so hazard warnings can never claim more than the asset's fragility allows:

    P(loss) = sig(l_H) sig(l_F) + (1 - sig(l_H)) sig(l_N)

Sums use `math.fsum` over a canonical order so replays hash identically. Signals caused by our own actions do
not raise risk (guard rule 1.6). Shapley attribution over roots is exact by enumeration.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from pathlib import Path

import yaml

MODEL_ID = "fusion.a3"
MODEL_VERSION = "1.0"
PARAMS_PATH = Path(__file__).with_name("fusion_params.yaml")
_PARAMS = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
DEFAULT_RHO = float(_PARAMS["rho"]["value"])
DEFAULT_CAP = float(_PARAMS["cap"]["value"])
MAX_EXACT_SHAPLEY_ROOTS = 14
_P_EPS = 1e-12


class Branch(StrEnum):
    HAZARD = "hazard"
    CONDITION = "condition"


class FusionMode(StrEnum):
    FLAT = "flat"
    SPLIT = "split"


@dataclass(frozen=True)
class Signal:
    root_id: str
    ln_lr: float
    branch: Branch = Branch.HAZARD
    caused_by_action_id: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.ln_lr):
            raise ValueError(f"signal on root {self.root_id} has a non-finite ln LR")


@dataclass(frozen=True)
class Priors:
    """Flat mode uses `p_loss`; split mode uses the three tree probabilities."""

    p_hazard: float
    p_loss_given_hazard: float
    p_loss_given_no_hazard: float

    def __post_init__(self) -> None:
        for name in ("p_hazard", "p_loss_given_hazard", "p_loss_given_no_hazard"):
            v = getattr(self, name)
            if not 0.0 < v < 1.0:
                raise ValueError(f"{name} must be strictly between 0 and 1")

    @property
    def p_loss(self) -> float:
        return self.p_hazard * self.p_loss_given_hazard + (1 - self.p_hazard) * self.p_loss_given_no_hazard


@dataclass(frozen=True)
class FusionConfig:
    rho: float = DEFAULT_RHO
    cap: float = DEFAULT_CAP
    mode: FusionMode = FusionMode.FLAT

    def __post_init__(self) -> None:
        if not 0.0 <= self.rho <= 1.0:
            raise ValueError("rho must be within [0, 1]")
        if not self.cap > 0:
            raise ValueError("cap must be positive")


@dataclass(frozen=True)
class RankedTerm:
    ln_lr: float
    weight: float
    term: float


@dataclass(frozen=True)
class RootEvidence:
    root_id: str
    branch: Branch
    value: float
    uncapped: float
    terms: tuple[RankedTerm, ...]
    excluded_own_action: int = 0


@dataclass(frozen=True)
class FusionResult:
    p_loss: float
    p_prior: float
    mode: FusionMode
    roots: tuple[RootEvidence, ...]
    shapley_pp: dict[str, float] = field(default_factory=dict)
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION


def logit(p: float) -> float:
    p = min(max(p, _P_EPS), 1 - _P_EPS)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def n_eff(k: int, rho: float) -> float:
    if k <= 0:
        return 0.0
    return k / (1 + (k - 1) * rho)


def _strongest_first(magnitudes: Iterable[float], rho: float) -> tuple[float, list[RankedTerm]]:
    ordered = sorted((m for m in magnitudes if m > 0), reverse=True)
    terms = []
    for k, x in enumerate(ordered, start=1):
        w = n_eff(k, rho) - n_eff(k - 1, rho)
        terms.append(RankedTerm(ln_lr=x, weight=w, term=w * x))
    return math.fsum(t.term for t in terms), terms


def root_value(ln_lrs: Sequence[float], rho: float = DEFAULT_RHO, cap: float = math.inf) -> float:
    return _root(ln_lrs, rho, cap)[0]


def _root(ln_lrs: Sequence[float], rho: float, cap: float) -> tuple[float, float, tuple[RankedTerm, ...]]:
    pos, pos_terms = _strongest_first((x for x in ln_lrs if x > 0), rho)
    neg, neg_terms = _strongest_first((-x for x in ln_lrs if x < 0), rho)
    neg_terms = [RankedTerm(ln_lr=-t.ln_lr, weight=t.weight, term=-t.term) for t in neg_terms]
    uncapped = pos - neg
    return max(-cap, min(cap, uncapped)), uncapped, tuple(pos_terms + neg_terms)


def coverage_ln_lr(
    *, fired: int, silent: int, reach: float, p_report_if_event: float, p_report_if_no_event: float
) -> float:
    """Signal plus silence for a group of reporters (e.g. meters under one device) with delivery reach `c`.
    A fired report keeps `ln(H/F)`; each silent reporter adds `ln((1 - cH) / (1 - cF))` (OSR 1.6)."""
    if fired < 0 or silent < 0:
        raise ValueError("counts must be non-negative")
    if not 0.0 <= reach <= 1.0:
        raise ValueError("reach must be within [0, 1]")
    h, f = p_report_if_event, p_report_if_no_event
    if not (0.0 < h < 1.0 and 0.0 < f < 1.0):
        raise ValueError("report rates must be strictly between 0 and 1")
    fired_term = fired * math.log(h / f) if fired else 0.0
    silent_term = silent * (math.log1p(-reach * h) - math.log1p(-reach * f)) if silent else 0.0
    return fired_term + silent_term


def root_evidence(signals: Sequence[Signal], config: FusionConfig) -> tuple[RootEvidence, ...]:
    grouped: dict[tuple[str, Branch], list[Signal]] = {}
    for s in signals:
        grouped.setdefault((s.root_id, s.branch), []).append(s)
    roots = []
    for (root_id, branch), group in sorted(grouped.items()):
        kept = [s.ln_lr for s in group if s.caused_by_action_id is None or s.ln_lr < 0]
        value, uncapped, terms = _root(kept, config.rho, config.cap)
        roots.append(
            RootEvidence(
                root_id=root_id,
                branch=branch,
                value=value,
                uncapped=uncapped,
                terms=terms,
                excluded_own_action=len(group) - len(kept),
            )
        )
    return tuple(roots)


def _probability(roots: Sequence[RootEvidence], priors: Priors, mode: FusionMode) -> float:
    if mode is FusionMode.FLAT:
        return sigmoid(logit(priors.p_loss) + math.fsum(r.value for r in roots))
    hazard = math.fsum(r.value for r in roots if r.branch is Branch.HAZARD)
    condition = math.fsum(r.value for r in roots if r.branch is Branch.CONDITION)
    p_h = sigmoid(logit(priors.p_hazard) + hazard)
    p_f = sigmoid(logit(priors.p_loss_given_hazard) + condition)
    p_n = sigmoid(logit(priors.p_loss_given_no_hazard) + condition)
    return p_h * p_f + (1 - p_h) * p_n


def shapley(roots: Sequence[RootEvidence], priors: Priors, mode: FusionMode) -> dict[str, float]:
    """Exact Shapley values (probability points, 0..100) over roots; they sum to P(all) - P(none)."""
    n = len(roots)
    if n == 0:
        return {}
    if n > MAX_EXACT_SHAPLEY_ROOTS:
        raise ValueError(f"exact Shapley supports at most {MAX_EXACT_SHAPLEY_ROOTS} roots, got {n}")
    keys = [f"{r.branch.value}:{r.root_id}" for r in roots]
    cache: dict[frozenset[int], float] = {}

    def value(subset: frozenset[int]) -> float:
        if subset not in cache:
            cache[subset] = _probability([roots[i] for i in sorted(subset)], priors, mode)
        return cache[subset]

    fact = [math.factorial(i) for i in range(n + 1)]
    out: dict[str, float] = {}
    for i in range(n):
        others = [j for j in range(n) if j != i]
        parts = []
        for size in range(n):
            weight = fact[size] * fact[n - size - 1] / fact[n]
            for combo in combinations(others, size):
                s = frozenset(combo)
                parts.append(weight * (value(s | {i}) - value(s)))
        out[keys[i]] = 100.0 * math.fsum(parts)
    return out


def fuse(
    signals: Sequence[Signal],
    priors: Priors,
    config: FusionConfig | None = None,
    *,
    attribution: bool = True,
) -> FusionResult:
    cfg = config or FusionConfig()
    roots = root_evidence(signals, cfg)
    return FusionResult(
        p_loss=_probability(roots, priors, cfg.mode),
        p_prior=priors.p_loss,
        mode=cfg.mode,
        roots=roots,
        shapley_pp=shapley(roots, priors, cfg.mode) if attribution else {},
    )
