from __future__ import annotations

import re
from pathlib import Path

import pytest

from sgw.common import numbers
from sgw.contracts import export
from sgw.contracts.vocab import ALL_VOCABS, NumberKind

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_drift_in_generated_artefacts() -> None:
    assert export.drift() == []


def test_numbers_outputs_have_no_drift() -> None:
    assert numbers.run(tex=True, py=True, ts=True, do_audit=False, check=True) == 0


def test_vocab_ts_and_sql_carry_every_enum_value() -> None:
    ts = (REPO_ROOT / "web/src/contracts/vocab.gen.ts").read_text()
    sql = (REPO_ROOT / "db/migrations/0002_contracts_vocab.sql").read_text()
    later = "\n".join(
        p.read_text() for p in sorted((REPO_ROOT / "db/migrations").glob("00[1-9]*_contracts_*.sql"))
    )
    for name, enum in ALL_VOCABS.items():
        m = re.search(rf"export const {name.upper()} = \[(.*?)\] as const;", ts)
        assert m, name
        assert re.findall(r'"([^"]*)"', m.group(1)) == [e.value for e in enum]
        d = re.search(rf"CREATE DOMAIN sgw_{name} AS text CHECK \(VALUE IN \((.*?)\)\);", sql)
        assert d, name
        altered = re.findall(rf"ADD CONSTRAINT sgw_{name}_check\s+CHECK \(VALUE IN \((.*?)\)\);", later, re.S)
        current = altered[-1] if altered else d.group(1)
        assert re.findall(r"'([^']*)'", current) == [e.value for e in enum]


ANCHORS = {
    "electric_customers_total": 4248290,
    "helene_footprint_peak_out": 2230592,
    "helene_hours_to_ninety_pct_restored": 204,
    "residents_sc": 5478831,
    "major_event_minutes_median": 162.6,
    "major_event_minutes_helene_year": 2358,
    "major_event_minutes_ratio": 14.5,
    "saidi_baseline_ga_min": 134,
    "price_haiku_input_usd_per_mtok": 0.10,
    "platform_cost_one_time_musd": 35.0,
    "sc_pressure_floor_psi": 25,
    "roi_utility_npv_musd": -17.6,
}


@pytest.mark.parametrize(("key", "expected"), sorted(ANCHORS.items()))
def test_section3_anchors(key: str, expected: float) -> None:
    assert numbers.value(key) == expected


def test_every_entry_labelled_sourced_and_policies_chipped() -> None:
    entries = numbers.numbers()
    assert len(entries) >= 50
    for key, e in entries.items():
        assert e.source and e.label and e.unit, key
        if e.kind is NumberKind.POLICY:
            assert e.chip == "Assumed SGW policy" and e.handoff_s3 is None
        else:
            assert e.handoff_s3, key
    assert numbers.value("policy_equity_weight") == 0
    assert (14.5 - 2358 / 162.6) ** 2 < 0.01


def test_never_quoted_values_absent() -> None:
    text = (REPO_ROOT / "data/numbers/numbers.yaml").read_text()
    for allowed in ("never use total_customers 7.2 M", "never 157 or 210.9", 'never "twentyfold"'):
        text = text.replace(allowed, "")
    for banned in ("7200000", "7.2 M", "210.9", "156.9", "twentyfold"):
        assert banned not in text


def test_audit_flags_literal_values(tmp_path: Path) -> None:
    (tmp_path / "data/numbers").mkdir(parents=True)
    (tmp_path / "data/numbers/numbers.yaml").write_text((REPO_ROOT / "data/numbers/numbers.yaml").read_text())
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/x.tex").write_text(
        "Helene left 2,230,592 customers out; macro \\numHeleneFootprintPeakOut.\n"
    )
    findings = numbers.audit(numbers.load(tmp_path / "data/numbers/numbers.yaml"), tmp_path)
    assert len(findings) == 1 and "helene_footprint_peak_out" in findings[0]
    (tmp_path / "docs/y.md").write_text("Containers run as uid 1000 and 2000.\n")
    assert len(numbers.audit(numbers.load(tmp_path / "data/numbers/numbers.yaml"), tmp_path)) == 1


STUB_KEYS_PROVIDED = {
    "footprint.residents",
    "footprint.customers_electric",
    "footprint.water_population",
    "storm.helene.peak_customers_out",
    "storm.helene.hours_to_90pct",
    "reliability.major_event_minutes",
    "reliability.major_event_median",
    "roi.cash.npv",
    "roi.cash.bcr",
    "roi.customer.npv",
    "roi.customer.bcr",
    "roi.customer.payback",
    "roi.breakeven_effect_multiple",
    "policy.breakglass_cosign_window",
    "policy.envelope_crew_band",
}


def test_tex_defines_wp05_keys_with_sgwdefnum() -> None:
    tex = (REPO_ROOT / "docs/latex/shared/numbers.tex").read_text()
    rows = re.findall(r"^\\sgwdefnum\{([^}]*)\}\{(.*)\}\{(.*)\}\{([FCAPSU])\}\{(.*)\}$", tex, re.M)
    keys = {r[0] for r in rows}
    assert keys >= STUB_KEYS_PROVIDED
    assert len(rows) == len(keys) == tex.count("\\sgwdefnum")
    assert dict((r[0], r[3]) for r in rows)["policy.envelope_crew_band"] == "P"
