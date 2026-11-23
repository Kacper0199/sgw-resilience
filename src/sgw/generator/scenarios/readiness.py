"""Readiness seeds (O-07, D-022): pre-season decisions on a blue-sky day, each with a rule deadline
(`clock_kind=rule_deadline`), so the decide-by idea works without a storm. The scenario clock is Monday
2024-05-06 08:00 EDT; the season deadline is 2024-06-01 00:00 EDT (A-083: emergency documents and readiness
are reviewed annually before June 1).

Clocks run end to end through WP-12 `compute_queue` (consequence `estimate` with one member: a rule deadline
has no spread, so P10 = P50 = P90; `critical_path` at P10/P50/P90; K16 `build_clock`); the readiness action
lead times live in WP-12's registry (`src/sgw/models/clocks/lead_times.yaml`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sgw.contracts.clocks import ClockBasis
from sgw.contracts.vocab import ClockKind, DecisionStep, Domain
from sgw.models.clocks.lead_times import LEAD_TIMES_PATH as LEAD_TIMES_PATH
from sgw.models.clocks.service import CaseSpec, QueueResult, compute_queue
from sgw.models.clocks.waterfall import ConsequenceSpec

NOW = datetime(2024, 5, 6, 12, 0, tzinfo=UTC)
SEASON_DEADLINE = datetime(2024, 6, 1, 4, 0, tzinfo=UTC)
LOAD_TEST_DUE = datetime(2024, 4, 24, 4, 0, tzinfo=UTC)
REGION = "SC-45003"
RULE_VERSION = "2024-synthetic"
SEASON_RULE = ClockBasis(
    kind=ClockKind.RULE_DEADLINE,
    basis_id="rule.readiness.hurricane_season_start",
    basis_version=RULE_VERSION,
    citation="A-083: annual readiness review before June 1 (hurricane season)",
)
LOAD_TEST_RULE = ClockBasis(
    kind=ClockKind.RULE_DEADLINE,
    basis_id="rule.readiness.generator_annual_load_test",
    basis_version=RULE_VERSION,
    citation="SGW maintenance policy: load test every 12 months; last test 2023-04-24 (synthetic)",
)


@dataclass(frozen=True)
class ReadinessSeed:
    case_id: str
    step: DecisionStep
    title: str
    domain: Domain
    lead_key: str
    rule: ClockBasis
    deadline_utc: datetime
    if_late: str
    asset_id: str
    work_type: str
    prerequisite_ids: tuple[str, ...] = ()
    priority: int = 0


SEEDS: tuple[ReadinessSeed, ...] = (
    ReadinessSeed(
        "DC-RDY-GEN-PS52-LOADTEST",
        DecisionStep.D3,
        "Run the overdue annual load test on GEN-PS52-DEERWATER",
        Domain.WATER,
        "generator_load_test",
        LOAD_TEST_RULE,
        LOAD_TEST_DUE,
        "PS-52 enters the season on an untested generator; in the Helene replay this unit stops at hour 30",
        "GEN-PS52-DEERWATER",
        "generator_load_test",
        priority=1,
    ),
    ReadinessSeed(
        "DC-RDY-FUEL-PS38-PS52-TOPUP",
        DecisionStep.D3,
        "Top up PS-38 and PS-52 generator tanks to five days at 70 % load and renew priority delivery",
        Domain.WATER,
        "fuel_contract_top_up",
        SEASON_RULE,
        SEASON_DEADLINE,
        "the onsite tanks start the season short of five days and the supplier owes no priority delivery",
        "GEN-PS38-COPPERLEAF",
        "fuel_contract_top_up",
        ("DC-RDY-GEN-PS52-LOADTEST",),
        priority=2,
    ),
    ReadinessSeed(
        "DC-RDY-VEG-FDR2207-2231",
        DecisionStep.D2,
        "Clear vegetation on the FDR-AIK-2207 (PS-17) and FDR-AIK-2231 (Tallowbranch hospital) trunks",
        Domain.ELECTRIC,
        "vegetation_clearance_critical_feeders",
        SEASON_RULE,
        SEASON_DEADLINE,
        "the two critical-facility trunks go into the season with tree contact risk on the weakest spans",
        "FDR-AIK-2207",
        "vegetation_clearance",
        priority=3,
    ),
    ReadinessSeed(
        "DC-RDY-STAGE-SANDHILL-LEASE",
        DecisionStep.D2,
        "Confirm the STG-AIK-SANDHILL-YARD lease and fuel-on-site terms",
        Domain.ELECTRIC,
        "staging_site_lease",
        SEASON_RULE,
        SEASON_DEADLINE,
        "the mutual-aid MOU cannot name a staging yard, so arriving crews have nowhere to stage",
        "STG-AIK-SANDHILL-YARD",
        "staging_site_lease",
        priority=4,
    ),
    ReadinessSeed(
        "DC-RDY-MAID-TALON-MOU",
        DecisionStep.D2,
        "Renew the mutual-aid MOU and roster with the Talon task force (CRW-MA-TALON-11)",
        Domain.ELECTRIC,
        "mutual_aid_mou_renewal",
        SEASON_RULE,
        SEASON_DEADLINE,
        "mutual aid is requested without agreed terms, adding negotiation time to the 36 h median arrival",
        "CRW-MA-TALON-11",
        "mutual_aid_mou",
        ("DC-RDY-STAGE-SANDHILL-LEASE",),
        priority=5,
    ),
    ReadinessSeed(
        "DC-RDY-TANKER-TALLOWBRANCH",
        DecisionStep.D3,
        "Sign a standby potable-water tanker agreement for HSP-AIK-TALLOWBRANCH",
        Domain.WATER,
        "potable_water_tanker_standby",
        SEASON_RULE,
        SEASON_DEADLINE,
        "if the hospital has power but no pressure (Helene D6), a tanker is sought ad hoc",
        "HSP-AIK-TALLOWBRANCH",
        "water_tanker_standby",
        priority=6,
    ),
)


def specs(seeds: Sequence[ReadinessSeed] = SEEDS) -> list[CaseSpec]:
    return [
        CaseSpec(
            case_id=s.case_id,
            step=s.step,
            title=s.title,
            domain=s.domain,
            region_id=REGION,
            consequence=ConsequenceSpec(
                consequence_basis=s.rule,
                anchor_label=f"rule deadline ({s.rule.basis_id})",
                anchor_basis=s.rule,
                anchor_utc=[s.deadline_utc],
            ),
            lead_key=s.lead_key,
            if_late=s.if_late,
            prerequisite_ids=s.prerequisite_ids,
        )
        for s in seeds
    ]


def queue(seeds: Sequence[ReadinessSeed] = SEEDS, *, now: datetime = NOW) -> QueueResult:
    """WP-12 `compute_queue` on the readiness specs (no share, no advisory: verdict n/a)."""
    return compute_queue(specs(seeds), now=now)
