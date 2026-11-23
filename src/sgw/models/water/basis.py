"""K16 clock bases the water twin publishes. WP-12 and WP-24 read these (or the copies in the PS-17 member
table under `water_twin`) instead of hard-coding ids: one basis per consequence term."""

from __future__ import annotations

from sgw.contracts.clocks import ClockBasis
from sgw.contracts.vocab import ClockKind
from sgw.models.water.floors import FlowCondition, State, service_floor
from sgw.models.water.params import twin_params


def drain_basis(state: State = State.SC, condition: FlowCondition = FlowCondition.NORMAL) -> ClockBasis:
    """Zone tank drain to the state floor at the critical service node: the consequence basis of the PS-17
    generator-hookup and pressure-hold cases and of the drain term."""
    tp = twin_params()
    return ClockBasis(
        kind=ClockKind.MODEL_ESTIMATE,
        basis_id=tp.model_ids["drain"],
        basis_version=tp.version,
        citation=service_floor(state, condition).citation,
    )


def generator_runtime_basis() -> ClockBasis:
    tp = twin_params()
    return ClockBasis(kind=ClockKind.MODEL_ESTIMATE, basis_id=tp.model_ids["fuel"], basis_version=tp.version)
