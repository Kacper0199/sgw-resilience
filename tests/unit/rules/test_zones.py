"""Zone rules: which decisions the Helene world raises at each scenario time, from data only."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sgw.approval.policy import ReferencePolicy
from sgw.contracts.vocab import ActionType, ClockKind
from sgw.rules import zones

MORNING_AFTER = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
NIGHT_2 = datetime(2024, 9, 28, 6, 0, tzinfo=UTC)
ETR = datetime(2024, 9, 28, 17, 0, tzinfo=UTC)
LIFTED = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
PS17_ORDERS = {"ps17_fuel_dispatch", "hospital_tanker"}


def keys(now: datetime) -> set[str]:
    return {h.key for h in zones.active(now)}


def raised_by(now: datetime) -> set[str]:
    return {h.key for h in zones.timeline() if h.known_at <= now}


def test_nothing_is_raised_before_the_act_now_advisory() -> None:
    assert keys(datetime(2024, 9, 26, 14, 59, tzinfo=UTC)) == set()
    act = zones.ps17_act_now(zones.world())
    assert act is not None and act.advisory == "N+1" and act.share_ppm >= act.threshold_ppm


def test_morning_after_raises_tanker_laurelspur_d7_and_the_dark_section() -> None:
    assert keys(MORNING_AFTER) == {"hospital_tanker_observed"} | {
        "bwa_issue:WZ-PS23-LAURELSPUR",
        "restoration_order",
        "ami_dark_section",
    }


def test_second_night_adds_the_ps38_fuel_reroute_and_copperleaf() -> None:
    assert raised_by(NIGHT_2) - raised_by(MORNING_AFTER) == {
        "ps38_fuel_reroute",
        "bwa_issue:WZ-PS38-COPPERLEAF",
    }


def test_etr_afternoon_adds_the_ps52_generator_and_deerwater() -> None:
    assert raised_by(ETR) - raised_by(NIGHT_2) == {"ps52_mobile_generator", "bwa_issue:WZ-PS52-DEERWATER"}


def test_lifts_by_30_sep_are_cedarfall_laurelspur_copperleaf_only() -> None:
    new = raised_by(LIFTED) - raised_by(ETR)
    assert new == {
        "bwa_lift:WZ-PS17-CEDARFALL",
        "bwa_lift:WZ-PS23-LAURELSPUR",
        "bwa_lift:WZ-PS38-COPPERLEAF",
    }
    assert "bwa_issue:WZ-PS52-DEERWATER" in keys(LIFTED)
    assert "bwa_issue:WZ-PS23-LAURELSPUR" not in keys(LIFTED)


def test_a_lift_needs_two_clean_sets_known_by_the_time() -> None:
    w = zones.world()
    assert zones.lift_of(w, "WZ-PS17-CEDARFALL", datetime(2024, 9, 29, 22, 20, tzinfo=UTC)) is None
    lift = zones.lift_of(w, "WZ-PS17-CEDARFALL", datetime(2024, 9, 29, 22, 21, tzinfo=UTC))
    assert lift is not None
    assert [s.sample_id for s in lift.samples] == ["LIMS-SYN-CEDARF-TC1", "LIMS-SYN-CEDARF-TC2"]
    assert [c for c, _ in lift.check.unmet] == ["SC-L4"]


def test_resolved_hits_stop_being_active() -> None:
    late = datetime(2024, 9, 28, 9, 0, tzinfo=UTC)
    assert "ps38_fuel_reroute" not in keys(late)
    assert "hospital_tanker_observed" not in keys(late)
    assert "hospital_tanker" not in keys(datetime(2024, 9, 27, 10, 5, tzinfo=UTC))


def test_the_observed_tanker_case_has_a_live_deadline_at_the_morning_after() -> None:
    (hit,) = zones.hospital_tanker_observed(zones.world())
    assert hit.known_at == datetime(2024, 9, 27, 10, 5, tzinfo=UTC)
    assert hit.clock is not None and hit.clock.lead_key == "potable_water_tanker"
    from sgw.models.clocks.service import compute_queue
    from sgw.models.clocks.zone_cases import case_spec

    case = compute_queue([case_spec(hit, "SC-45003")]).cases[hit.case_id].case
    assert case.effective_decide_by_utc == datetime(2024, 9, 27, 14, 5, tzinfo=UTC)


@pytest.mark.parametrize("hit", zones.timeline(), ids=lambda h: h.key)
def test_every_clock_cites_a_basis_and_every_number_is_canonical(hit: zones.ZoneHit) -> None:
    assert hit.params["known_at_utc"] == zones.iso(hit.known_at)
    assert hit.params["rule_id"].startswith("rule.")
    for value in hit.params.values():
        assert isinstance(value, int | str | bool | list)
    assert hit.rationale and "{" not in hit.rationale
    if hit.clock is not None:
        assert hit.clock.consequence_basis.basis_id
        assert hit.clock.anchor_basis.basis_id
        assert all(t.basis.basis_id for t in hit.clock.terms)
    if hit.action_type is ActionType.BOIL_WATER_NOTICE:
        assert hit.clock is not None and hit.clock.consequence_basis.kind is ClockKind.RULE_DEADLINE


@pytest.mark.parametrize("hit", zones.timeline(), ids=lambda h: h.key)
def test_the_reference_policy_lets_each_rule_propose(hit: zones.ZoneHit) -> None:
    decision = ReferencePolicy().propose(
        {
            "action": "propose",
            "subject": {"user_id": hit.proposer},
            "proposal": {
                "action_type": hit.action_type.value,
                "proposed_by": hit.proposer,
                "requested_by": None,
                "initiator_kind": "system_rule",
                "target_ids": list(hit.target_ids),
            },
            "facts": {"customers_affected": 0},
            "context": {"degraded_mode": "M0"},
        }
    )
    assert decision.allow, decision.deny


def test_d7_ranks_by_ce_with_the_hospital_counted_through_water() -> None:
    (hit,) = zones.restoration_order(zones.world())
    assert hit.params["priority"] == ["FDR-AIK-2219", "FDR-AIK-2207"]
    assert hit.params["ce_FDR-AIK-2207"] == 3840 and hit.params["ce_FDR-AIK-2219"] == 3960


def test_the_dark_section_is_an_anomaly_row_only_with_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from sgw.api.readmodels import anomalies
    from sgw.models.clocks import zone_cases

    monkeypatch.delenv(zone_cases.FLAG_ENV, raising=False)
    off = anomalies.anomalies(MORNING_AFTER)
    assert not any(a.anomaly_class == "ami_dark_section" for a in off)
    monkeypatch.setenv(zone_cases.FLAG_ENV, "1")
    on = anomalies.anomalies(MORNING_AFTER)
    (dark,) = [a for a in on if a.anomaly_class == "ami_dark_section"]
    assert dark.entity_id == "FDR-AIK-2231-S3" and dark.detected_at == datetime(
        2024, 9, 27, 8, 15, tzinfo=UTC
    )
    assert len(on) == len(off) + 1
    assert [a.detected_at for a in on] == sorted((a.detected_at for a in on), reverse=True)
    assert not any(
        a.anomaly_class == "ami_dark_section"
        for a in anomalies.anomalies(datetime(2024, 9, 27, 8, 0, tzinfo=UTC))
    )
