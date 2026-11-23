"""Milestone plans: what an approved decision promises and how each step is observed.

A commitment promises the decision case's consequence time (`promised_by_utc`): the action and the steps it
protects must be complete before the clock's consequence. Milestones are scheduled backwards from that
promise by the K16 lead times of the chain (the latest-finish times of the critical path), so a milestone due
time is the last moment it can happen without moving the promise. Each milestone names the ledger signal
that marks it met (a work-order status, a crew status, a pressure reading at or above the state floor).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.common import numbers
from sgw.models.clocks import lead_times

POLICY_PATH = Path(__file__).with_name("policy.yaml")
LEAD_PREFIX = "lead_time."


@cache
def _policy() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    return raw


NUMBER_KEYS = {
    "drift_tolerance_min": "policy_commitment_drift_tolerance_min",
    "credibility_prior_n": "policy_learning_credibility_prior_n",
    "min_change_min": "policy_learning_min_change_min",
    "rounding_min": "policy_learning_rounding_min",
}


def policy_value(key: str) -> Any:
    """A commitment policy parameter: numeric ones from numbers.yaml (K10), the rest from policy.yaml."""
    if key in NUMBER_KEYS:
        return numbers.value(NUMBER_KEYS[key])
    try:
        return _policy()["policy"][key]["value"]
    except KeyError as exc:
        raise KeyError(f"no commitment policy parameter {key!r}") from exc


def policy_version() -> str:
    return str(_policy()["version"])


def drift_tolerance_min() -> int:
    return int(policy_value("drift_tolerance_min"))


@dataclass(frozen=True)
class StepSpec:
    name: str
    signal: Mapping[str, Any]
    after_keys: tuple[str, ...]
    lead_key: str | None = None


@dataclass(frozen=True)
class Milestone:
    seq: int
    name: str
    due_utc: datetime
    remaining_min: int
    signal: Mapping[str, Any]
    lead_key: str | None = None
    met_utc: datetime | None = None
    met_event_id: str | None = None


@dataclass(frozen=True)
class Plan:
    lead_key: str
    promised_by_utc: datetime
    milestones: tuple[Milestone, ...] = field(default_factory=tuple)


def _wo(work_type: str, statuses: Sequence[str], asset: str = "$station") -> dict[str, Any]:
    return {"type": "WorkOrder", "work_type": work_type, "status_in": list(statuses), "asset_id": asset}


def _steps(lead_key: str) -> tuple[StepSpec, ...] | None:
    floor = float(numbers.value("sc_pressure_floor_psi"))
    plans: dict[str, tuple[StepSpec, ...]] = {
        "portable_generator_hookup": (
            StepSpec(
                "generator hookup crew dispatched",
                _wo("portable_generator_hookup", ("open", "in_progress", "closed")),
                ("portable_generator_hookup", "pump_restart_refill"),
                "portable_generator_hookup",
            ),
            StepSpec(
                "generator connected and running",
                _wo("portable_generator_hookup", ("in_progress", "closed")),
                ("pump_restart_refill",),
                "portable_generator_hookup",
            ),
            StepSpec(
                "zone pressure held above the state floor",
                {
                    "type": "DeviceState",
                    "device_kind": "pressure_sensor",
                    "asset_id": "$station",
                    "min_value": floor,
                    "after_seq": 2,
                },
                (),
                "pump_restart_refill",
            ),
        ),
        "fuel_truck_dispatch": (
            StepSpec(
                "fuel truck departed",
                _wo("fuel_delivery", ("open", "in_progress", "closed"), "$generator"),
                ("fuel_truck_dispatch",),
                "fuel_truck_dispatch",
            ),
            StepSpec(
                "fuel delivered to the generator",
                _wo("fuel_delivery", ("closed",), "$generator"),
                (),
                "fuel_truck_dispatch",
            ),
        ),
        "crew_mobilise_and_stage": (
            StepSpec(
                "crews en route to the staging yards",
                {"type": "CrewStatus", "status_in": ["enroute"], "location_in": "$targets"},
                ("crew_mobilise_and_stage",),
                "crew_mobilise_and_stage",
            ),
            StepSpec(
                "crews staged at every target yard",
                {
                    "type": "CrewStatus",
                    "status_in": ["staged"],
                    "location_in": "$targets",
                    "all_locations": True,
                },
                (),
                "crew_mobilise_and_stage",
            ),
        ),
    }
    return plans.get(lead_key)


def lead_key_of(lead_time_basis: Mapping[str, Any]) -> str | None:
    basis_id = str(lead_time_basis.get("basis_id", ""))
    return basis_id[len(LEAD_PREFIX) :] if basis_id.startswith(LEAD_PREFIX) else None


def supported(lead_key: str | None) -> bool:
    return lead_key is not None and _steps(lead_key) is not None


def _bind(signal: Mapping[str, Any], bindings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        k: bindings.get(v, v) if isinstance(v, str) and v.startswith("$") else v for k, v in signal.items()
    }


def build_plan(
    lead_key: str,
    promised_by_utc: datetime,
    bindings: Mapping[str, Any],
    minutes: Mapping[str, int] | None = None,
) -> Plan:
    """Milestones for one approved case, latest-finish scheduled from the promise. `minutes` overrides the
    registry (tests and what-if); by default the current K16 lead-time policy is used."""
    steps = _steps(lead_key)
    if steps is None:
        raise KeyError(f"no milestone plan for lead time {lead_key!r}")

    def lead(key: str) -> int:
        return int(minutes[key]) if minutes and key in minutes else lead_times.lead_time(key).minutes

    out = []
    for seq, step in enumerate(steps, start=1):
        remaining = sum(lead(k) for k in step.after_keys)
        out.append(
            Milestone(
                seq=seq,
                name=step.name,
                due_utc=promised_by_utc - timedelta(minutes=remaining),
                remaining_min=remaining,
                signal=_bind(step.signal, bindings),
                lead_key=step.lead_key,
            )
        )
    return Plan(lead_key=lead_key, promised_by_utc=promised_by_utc, milestones=tuple(out))
