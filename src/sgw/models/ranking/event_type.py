"""D1 event-type recommendation (DC-31 Type 5 routine .. Type 1 catastrophic) with analog storms.

The type is the more severe of two criteria: predicted peak share of footprint electric customers out, and
predicted hours to 90% restored. The recommendation uses the P50 forecast; the P90 type is reported as the
escalation a planner should be ready for. Analogs are real storms ranked by log distance between their
footprint-equivalent peak share and the predicted P50 share; statewide-basis storms carry no implied type, and
the scenario's own storm is never its own analog. The
platform recommends; the IC sets the type (T2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sgw.common import numbers as numbers_mod
from sgw.models.ranking.params import params

MODEL_ID = "ranking.event_type"
MODEL_VERSION = "1.0"


@dataclass(frozen=True)
class Threshold:
    type: int
    name: str
    max_peak_share: float | None
    max_t90_h: float | None


@dataclass(frozen=True)
class Analog:
    storm: str
    year: int
    peak_customers_out: int
    basis: str
    footprint_equivalent_share: float
    implied_type: int | None
    distance: float


@dataclass(frozen=True)
class EventTypeRecommendation:
    recommended_type: int
    recommended_name: str
    driver: str
    escalation_type: int
    peak_share_p50: float
    peak_share_p90: float
    t90_h_p50: float | None
    analogs: tuple[Analog, ...]
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION


def thresholds() -> list[Threshold]:
    rows = [Threshold(**t) for t in params()["event_types"]["thresholds"]]
    return sorted(rows, key=lambda t: -t.type)


def _type_by(value: float, attr: str) -> int:
    for t in thresholds():
        limit = getattr(t, attr)
        if limit is None or value < limit:
            return t.type
    return 1


def classify(peak_share: float, t90_h: float | None = None) -> tuple[int, str]:
    by_share = _type_by(peak_share, "max_peak_share")
    by_time = _type_by(t90_h, "max_t90_h") if t90_h is not None else 5
    if by_time < by_share:
        return by_time, "time to 90% restored"
    return by_share, "peak customers out"


def footprint_customers() -> int:
    return int(numbers_mod.value("electric_customers_total"))


def _basis_factor(basis: str) -> float:
    if basis == "footprint":
        return 1.0
    scaling = params()["analogs"]["basis_scaling"][basis]
    return float(numbers_mod.value(scaling["numerator_key"])) / float(
        numbers_mod.value(scaling["denominator_key"])
    )


def analogs(peak_share: float, k: int = 3, exclude_storm: str | None = None) -> tuple[Analog, ...]:
    """Nearest real storms by log distance of footprint-equivalent peak share. Only footprint-basis storms get
    an implied type; the scenario's own storm is excluded."""
    total = footprint_customers()
    out = []
    for s in params()["analogs"]["storms"]:
        if exclude_storm is not None and s["storm"].lower() == exclude_storm.lower():
            continue
        peak = int(numbers_mod.value(s["peak_key"]))
        share = peak * _basis_factor(s["basis"]) / total
        out.append(
            Analog(
                storm=s["storm"],
                year=int(s["year"]),
                peak_customers_out=peak,
                basis=s["basis"],
                footprint_equivalent_share=share,
                implied_type=classify(share)[0] if s["basis"] == "footprint" else None,
                distance=abs(math.log(max(share, 1e-9)) - math.log(max(peak_share, 1e-9))),
            )
        )
    return tuple(sorted(out, key=lambda a: (a.distance, a.storm))[:k])


def recommend(
    *,
    peak_customers_out_p50: float,
    peak_customers_out_p90: float,
    t90_h_p50: float | None = None,
    t90_h_p90: float | None = None,
    scenario_storm: str | None = None,
) -> EventTypeRecommendation:
    if not 0 <= peak_customers_out_p50 <= peak_customers_out_p90:
        raise ValueError("need 0 <= P50 <= P90 peak customers out")
    total = footprint_customers()
    s50, s90 = peak_customers_out_p50 / total, peak_customers_out_p90 / total
    rec, driver = classify(s50, t90_h_p50)
    esc, _ = classify(s90, t90_h_p90 if t90_h_p90 is not None else t90_h_p50)
    name = {t.type: t.name for t in thresholds()}[rec]
    return EventTypeRecommendation(
        recommended_type=rec,
        recommended_name=name,
        driver=driver,
        escalation_type=min(esc, rec),
        peak_share_p50=s50,
        peak_share_p90=s90,
        t90_h_p50=t90_h_p50,
        analogs=analogs(s50, exclude_storm=scenario_storm),
    )
