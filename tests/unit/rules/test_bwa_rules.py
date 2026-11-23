"""One test per clause of the boil-water rules engine (`src/sgw/rules/bwa_rules.yaml`). Each test names the
clause it exercises and the text it rests on:

SC-P1 / SC-P2  S.C. Code Regs. R.61-58.7.E(7): 25 psi normal, 20 psi heavy flow, at the service connection
SC-A1          SC DES Boil Water Notices and Advisories (2024): advisory for loss of pressure
SC-A2          same guidance: advisory prior to a hurricane making landfall (SGW threshold, numbers.yaml)
SC-N1          same guidance: notice when sampling confirms
SC-C1, SC-I1   same guidance (regulator told immediately, copy, repeal) and SGW WQC 07.120 6.2-6.3
SC-L1, SC-L2, SC-L3, SC-L4  same guidance (flush and sample; two sets 24 h apart; hurricane
               repeal) and WQC 07.120 6.4.3
GA-P1          Ga. Comp. R. & Regs. 391-3-5-.10: 20 psi at each service connection, all flows
GA-C1, GA-I1   SGW WQC 07.114 6.2.1, 6.2.4, 6.3.3, 6.3.4
GA-L1          GA EPD protocol (A-085) and WQC 07.114 6.4.1-6.4.4
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sgw.common import numbers as numbers_mod
from sgw.models.water.floors import State
from sgw.rules import bwa
from sgw.rules.bwa import Cause, LiftEvidence, NoticeKind, PressureReading, SampleSet

T0 = datetime(2024, 9, 27, 12, 0, tzinfo=UTC)
LANDFALL = datetime(2024, 9, 27, 3, 10, tzinfo=UTC)
ZONE = "WZ-PS17-CEDARFALL"
HOSPITAL = "HSP-AIK-TALLOWBRANCH"


def _reading(
    psi: float, *, connection: bool = True, heavy: bool = False, minutes: int = 0
) -> PressureReading:
    return PressureReading("J-CF-TALLOWBRANCH", T0 + timedelta(minutes=minutes), psi, connection, heavy)


def _set(hours: float, positive: int = 0, samples: int = 10, sites: int = 10) -> SampleSet:
    return SampleSet(
        T0 + timedelta(hours=hours), samples, tuple(f"CS-{i:02d}" for i in range(sites)), positive
    )


# ---- floors and triggers ----------------------------------------------------------------------------------


def test_sc_p1_normal_operation_floor_is_25_psi_at_the_service_connection() -> None:
    assert numbers_mod.value("sc_pressure_floor_psi") == 25
    assert bwa.pressure_hits(State.SC, ZONE, [_reading(25.0)]) == []
    [hit] = bwa.pressure_hits(State.SC, ZONE, [_reading(24.9)])
    assert hit.detail["floor_clause"] == "SC-P1" and hit.detail["floor_psi"] == 25.0
    assert bwa.rulebook().clause("SC-P1").citation == "S.C. Code Regs. R.61-58.7.E(7)"


def test_sc_p2_heavy_flow_floor_is_20_psi() -> None:
    assert numbers_mod.value("sc_pressure_floor_heavy_flow_psi") == 20
    assert bwa.pressure_hits(State.SC, ZONE, [_reading(22.0, heavy=True)]) == []
    [hit] = bwa.pressure_hits(State.SC, ZONE, [_reading(19.5, heavy=True)])
    assert hit.detail["floor_clause"] == "SC-P2"


def test_floors_apply_at_the_service_connection_not_the_station_sensor() -> None:
    assert bwa.pressure_hits(State.SC, ZONE, [_reading(5.0, connection=False)]) == []
    assert bwa.pressure_hits(State.GA, ZONE, [_reading(5.0, connection=False)]) == []


def test_sc_a1_loss_of_pressure_makes_a_precautionary_advisory() -> None:
    [hit] = bwa.pressure_hits(State.SC, ZONE, [_reading(18.0)])
    assert hit.clause.clause_id == "SC-A1"
    assert (hit.kind, hit.cause, hit.due_utc) == (NoticeKind.ADVISORY, Cause.PRESSURE_LOSS, T0)
    assert "loss of pressure" in hit.clause.summary


def test_sc_a2_pre_landfall_advisory_fires_at_the_policy_threshold_before_landfall() -> None:
    p_star = float(numbers_mod.value("policy_pre_landfall_breach_p"))
    now = LANDFALL - timedelta(hours=12)
    kw = {
        "state": State.SC,
        "zone_id": ZONE,
        "now": now,
        "landfall_utc": LANDFALL,
        "on_backup_or_exposed": True,
    }
    hit = bwa.pre_landfall_hit(breach_p=p_star, **kw)
    assert hit is not None and hit.clause.clause_id == "SC-A2"
    assert (hit.kind, hit.cause, hit.due_utc) == (NoticeKind.ADVISORY, Cause.PRE_HURRICANE, LANDFALL)
    assert bwa.pre_landfall_hit(breach_p=p_star - 0.01, **kw) is None
    assert bwa.pre_landfall_hit(breach_p=0.9, **{**kw, "on_backup_or_exposed": False}) is None
    assert bwa.pre_landfall_hit(breach_p=0.9, **{**kw, "now": LANDFALL}) is None
    assert bwa.pre_landfall_hit(breach_p=0.9, **{**kw, "state": State.GA}) is None


def test_sc_n1_confirmed_positive_makes_it_a_notice() -> None:
    hit = bwa.positive_sample_hit(State.SC, ZONE, confirmed_at=T0)
    assert hit is not None and hit.kind is NoticeKind.NOTICE and hit.clause.clause_id == "SC-N1"
    assert bwa.positive_sample_hit(State.SC, ZONE, confirmed_at=None) is None


def test_ga_p1_floor_is_20_psi_under_all_flows() -> None:
    assert numbers_mod.value("ga_pressure_floor_psi") == 20
    assert bwa.pressure_hits(State.GA, ZONE, [_reading(22.0), _reading(20.0, heavy=True)]) == []
    hits = bwa.pressure_hits(State.GA, ZONE, [_reading(19.9), _reading(19.9, heavy=True, minutes=5)])
    assert [h.clause.clause_id for h in hits] == ["GA-P1", "GA-P1"]
    assert bwa.rulebook().clause("GA-P1").citation == "Ga. Comp. R. & Regs. 391-3-5-.10"


# ---- lift -------------------------------------------------------------------------------------------------


def test_sc_l1_pressure_loss_advisory_lifts_after_flushing_and_negative_samples() -> None:
    flushed = T0 + timedelta(hours=2)
    ok = LiftEvidence(
        pressure_restored=True, flushed_utc=flushed, sample_sets=[_set(4)], regulator_concurs=True
    )
    check = bwa.lift_check(State.SC, Cause.PRESSURE_LOSS, ok)
    assert check.may_lift and "SC-L1" in check.met
    before_flush = LiftEvidence(
        pressure_restored=True, flushed_utc=flushed, sample_sets=[_set(1)], regulator_concurs=True
    )
    bad = bwa.lift_check(State.SC, Cause.PRESSURE_LOSS, before_flush)
    assert not bad.may_lift and ("SC-L1", "no coliform samples after flushing") in bad.unmet
    no_pressure = bwa.lift_check(State.SC, Cause.PRESSURE_LOSS, LiftEvidence(pressure_restored=False))
    assert ("SC-L1", "pressure not restored") in no_pressure.unmet


def test_sc_l2_notice_needs_two_negative_sets_at_least_24_h_apart() -> None:
    flushed = T0
    one_day = LiftEvidence(
        pressure_restored=True,
        flushed_utc=flushed,
        sample_sets=[_set(1), _set(25)],
        regulator_concurs=True,
    )
    assert bwa.lift_check(State.SC, Cause.POSITIVE_SAMPLE, one_day).may_lift
    too_close = LiftEvidence(
        pressure_restored=True, flushed_utc=flushed, sample_sets=[_set(1), _set(20)], regulator_concurs=True
    )
    check = bwa.lift_check(State.SC, Cause.POSITIVE_SAMPLE, too_close)
    assert not check.may_lift and check.unmet[0][0] == "SC-L2"
    assert bwa.rulebook().f("sc_lift_sample_set_gap_h") == 24


def test_sc_l3_pre_hurricane_advisory_repeals_without_sampling_when_no_pressure_was_lost() -> None:
    no_loss = LiftEvidence(
        pressure_restored=True, lost_pressure=False, quality_maintained=True, regulator_concurs=True
    )
    check = bwa.lift_check(State.SC, Cause.PRE_HURRICANE, no_loss)
    assert check.may_lift and check.path == "pre_hurricane_no_loss" and "SC-L3" in check.met
    lost = LiftEvidence(
        pressure_restored=True, lost_pressure=True, quality_maintained=True, regulator_concurs=True
    )
    check = bwa.lift_check(State.SC, Cause.PRE_HURRICANE, lost)
    assert not check.may_lift and check.path == "pre_hurricane_with_loss"
    assert any(c == "SC-L1" for c, _ in check.unmet)
    unevaluated = bwa.lift_check(State.SC, Cause.PRE_HURRICANE, LiftEvidence(pressure_restored=True))
    assert not unevaluated.may_lift and unevaluated.unmet[0][0] == "SC-L3"


def test_sc_l4_lift_needs_scdes_agreement_and_all_negative() -> None:
    ev = LiftEvidence(pressure_restored=True, flushed_utc=T0, sample_sets=[_set(4)], regulator_concurs=False)
    check = bwa.lift_check(State.SC, Cause.PRESSURE_LOSS, ev)
    assert not check.may_lift and ("SC-L4", "SCDES agreement not recorded") in check.unmet
    positive = LiftEvidence(
        pressure_restored=True, flushed_utc=T0, sample_sets=[_set(4, positive=1)], regulator_concurs=True
    )
    assert any(c == "SC-L4" for c, _ in bwa.lift_check(State.SC, Cause.PRESSURE_LOSS, positive).unmet)


def _ga(**kw: object) -> LiftEvidence:
    base: dict[str, object] = {
        "pressure_restored": True,
        "integrity_restored": True,
        "flushed_utc": T0,
        "sample_sets": [_set(24, sites=20, samples=20)],
        "regulator_concurs": True,
        "coliform_sites_total": 40,
    }
    return LiftEvidence(**{**base, **kw})  # type: ignore[arg-type]


def test_ga_l1_rescission_conditions_a_to_d_wait_and_concurrence() -> None:
    assert bwa.lift_check(State.GA, Cause.PRESSURE_LOSS, _ga()).may_lift
    cases = {
        "integrity": _ga(integrity_restored=False),
        "flush": _ga(flushed_utc=None),
        "wait": _ga(sample_sets=[_set(23, sites=20, samples=20)]),
        "share": _ga(sample_sets=[_set(24, sites=19, samples=19)]),
        "negative": _ga(sample_sets=[_set(24, sites=20, samples=20, positive=1)]),
        "concurrence": _ga(regulator_concurs=False),
    }
    for name, ev in cases.items():
        check = bwa.lift_check(State.GA, Cause.PRESSURE_LOSS, ev)
        assert not check.may_lift, name
        assert all(c == "GA-L1" for c, _ in check.unmet), name


def test_ga_l1_inspector_accepted_sample_count_replaces_the_site_share() -> None:
    few_sites = [_set(24, sites=5, samples=16)]
    ok = bwa.lift_check(
        State.GA, Cause.PRESSURE_LOSS, _ga(sample_sets=few_sites, inspector_accepted_samples=15)
    )
    assert ok.may_lift
    short = bwa.lift_check(
        State.GA, Cause.PRESSURE_LOSS, _ga(sample_sets=few_sites, inspector_accepted_samples=20)
    )
    assert not short.may_lift
    with pytest.raises(bwa.RuleError):
        bwa.lift_check(State.GA, Cause.PRESSURE_LOSS, _ga(inspector_accepted_samples=12))


# ---- lifecycle tasks, regulator communication, notice draft -----------------------------------------------


def _pre_landfall_hit() -> bwa.RuleHit:
    hit = bwa.pre_landfall_hit(
        state=State.SC,
        zone_id=ZONE,
        now=LANDFALL - timedelta(hours=12),
        landfall_utc=LANDFALL,
        breach_p=0.5,
        on_backup_or_exposed=True,
    )
    assert hit is not None
    return hit


def test_sc_c1_regulator_is_told_immediately_on_issue_and_on_repeal() -> None:
    tasks = bwa.lifecycle_tasks(_pre_landfall_hit(), critical_customers=[HOSPITAL])
    c1 = [t for t in tasks if t.clause_id == "SC-C1"]
    assert [t.due_rule for t in c1] == ["immediately on issue", "as soon as possible", "on repeal"]
    assert c1[0].phase == "issue" and c1[-1].phase == "lift"
    assert all(t.owner_function == "compliance" for t in c1)


def test_sc_i1_critical_customers_hear_first_and_written_notice_follows_in_the_window() -> None:
    tasks = bwa.lifecycle_tasks(_pre_landfall_hit(), critical_customers=[HOSPITAL])
    i1 = [t for t in tasks if t.clause_id == "SC-I1"]
    assert HOSPITAL in i1[0].title and i1[0].due_rule.startswith("first")
    assert i1[1].due_rule == "within 4 h of the verbal notice"
    titles = [t.title for t in tasks]
    assert titles.index(i1[0].title) < titles.index(i1[1].title)
    first = tasks[0]
    assert (first.clause_id, first.due_utc) == ("SC-A2", LANDFALL)
    assert any(t.clause_id == "SC-L3" and t.phase == "monitor" for t in tasks)
    assert [t.task_id for t in tasks] == [f"BWA-{ZONE}-{i:02d}" for i in range(1, len(tasks) + 1)]


def test_ga_c1_and_ga_i1_tasks() -> None:
    [hit] = bwa.pressure_hits(State.GA, ZONE, [_reading(15.0)])
    tasks = bwa.lifecycle_tasks(hit, critical_customers=[HOSPITAL])
    by_clause = {t.clause_id: [] for t in tasks}  # type: dict[str, list[str]]
    for t in tasks:
        by_clause[t.clause_id].append(t.due_rule)
    assert by_clause["GA-C1"] == ["before the public notice where possible", "within 24 h"]
    assert by_clause["GA-I1"] == ["within 2 h of the decision", "on release"]
    assert "no sooner than 24 h after flushing" in by_clause["GA-L1"]


def test_notice_draft_cites_the_clause_and_the_in_force_sop() -> None:
    as_of = datetime(2024, 9, 26, 15, 0, tzinfo=UTC)
    draft = bwa.notice_draft(
        _pre_landfall_hit(),
        zone_name="Cedarfall",
        as_of=as_of,
        cause_text="Because Hurricane Helene may cause a loss of water pressure,",
    )
    assert draft.clause_id == "SC-A2"
    assert draft.clause == (
        "SC DES, Boil Water Notices and Advisories (2024): advisory prior to a hurricane making landfall"
    )
    assert draft.template == "WQC 07.120 Rev C Attachment A"
    assert draft.title.startswith("BOIL WATER ADVISORY")
    assert "South Carolina Department of Environmental Services (SCDES)" in draft.body
    assert "[date and time of release]" in draft.body and "next update" in draft.body


def test_ga_l1_counts_unique_coliform_sites() -> None:
    same_sites = [_set(24, sites=20, samples=20), _set(30, sites=20, samples=20)]
    check = bwa.lift_check(
        State.GA, Cause.PRESSURE_LOSS, _ga(sample_sets=same_sites, coliform_sites_total=50)
    )
    assert not check.may_lift and ("GA-L1", "too few coliform sites or samples") in check.unmet


@pytest.mark.parametrize("cid", sorted(bwa.rulebook().clauses))
def test_cited_sop_section_text_supports_the_clause(cid: str) -> None:
    clause = bwa.rulebook().clause(cid)
    sop = bwa.sop_citation(clause, datetime(2024, 9, 26, tzinfo=UTC))
    if clause.sop is None:
        assert sop is None
        return
    assert sop is not None and clause.sop.supports
    for phrase in clause.sop.supports:
        assert phrase.lower() in sop.section_text.lower(), (cid, phrase, sop.section_text)


def test_sc_a2_has_no_sop_section_and_a_wrong_section_is_refused() -> None:
    import dataclasses

    clause = bwa.rulebook().clause("SC-A2")
    assert clause.sop is None
    wrong = dataclasses.replace(clause, sop=bwa.SopRef("WQC 07.120", "6.1.2", ("landfall",)))
    with pytest.raises(bwa.RuleError, match="does not say"):
        bwa.sop_citation(wrong, datetime(2024, 9, 26, tzinfo=UTC))


def test_section_text_stops_at_the_next_numbered_line() -> None:
    body = "6.4.1 Rescission requires all of the following:\n\na. one;\n\nb. two.\n\n6.4.2 Collect later."
    assert (
        bwa.section_text(body, "6.4.1") == "6.4.1 Rescission requires all of the following: a. one; b. two."
    )
    assert bwa.section_text(body, "6.4.9") is None


def test_sop_citation_follows_the_revision_in_force() -> None:
    clause = bwa.rulebook().clause("SC-A1")
    before = bwa.sop_citation(clause, datetime(2023, 1, 10, tzinfo=UTC))
    after = bwa.sop_citation(clause, datetime(2024, 9, 26, tzinfo=UTC))
    assert before is not None and after is not None
    assert (before.citation_id, after.citation_id) == ("WQC 07.120 Rev B", "WQC 07.120 Rev C")
    with pytest.raises(bwa.RuleError):
        bwa.sop_citation(clause, datetime(2001, 1, 1, tzinfo=UTC))


def test_every_clause_is_tested_and_cited() -> None:
    import pathlib
    import re

    book = bwa.rulebook()
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    for cid, clause in book.clauses.items():
        assert clause.citation and clause.label in ("F", "A"), cid
        assert re.search(rf"\b{re.escape(cid)}\b", src.split('"""', 2)[1]), f"{cid} missing from the header"
        assert f'"{cid}"' in src or f"{cid.lower().replace('-', '_')}_" in src, f"{cid} has no test"
        if clause.sop is not None:
            assert bwa.sop_citation(clause, datetime(2024, 9, 26, tzinfo=UTC)) is not None, cid
