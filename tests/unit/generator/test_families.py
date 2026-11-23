"""Family A / family B separation (DC-15): same keys, shifted values, B never read by family-A runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from sgw.common import numbers as numbers_mod
from sgw.generator.config import FAMILY_FILES, SYNTHETIC_DIR, load_family
from sgw.generator.truth import run_truth

SHIFTED = (
    "fragility.median_gust_ms",
    "fragility.beta",
    "fragility.county_effect_sigma",
    "fragility.veg_median_reduction",
    "telemetry.evidence_shared_draw_rho",
    "water.pressure_noise_psi",
)


def test_families_have_the_same_parameters_with_labels_and_sources() -> None:
    a, b = load_family("A"), load_family("B")
    assert set(a.params) == set(b.params)
    for fam in (a, b):
        for p in fam.params.values():
            assert p.label in {"F", "C", "A", "I"} and p.source


def test_family_b_shifts_the_dc15_parameters() -> None:
    a, b = load_family("A"), load_family("B")
    for key in SHIFTED:
        assert a[key] != b[key], key
    assert b.f("telemetry.evidence_shared_draw_rho") == pytest.approx(0.7)
    ratio = b.f("fragility.median_gust_ms") / a.f("fragility.median_gust_ms")
    assert 0.87 <= ratio <= 1.12


def test_numbers_backed_parameters_come_from_numbers_yaml() -> None:
    a = load_family("A")
    assert a["fragility.median_gust_ms"] == numbers_mod.value("fragility_median_gust_ms")
    assert a["restoration.mutual_aid_median_h"] == numbers_mod.value("mutual_aid_arrival_median_hours")
    assert a["water.floor_psi"] == numbers_mod.value("sc_pressure_floor_psi")


def test_family_a_run_never_reads_family_b(scenario: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    original = Path.read_text

    def spy(self: Path, *args: object, **kwargs: object) -> str:
        seen.append(self.name)
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", spy)
    run_truth(scenario, load_family("A"))
    assert FAMILY_FILES["A"] in seen
    assert FAMILY_FILES["B"] not in seen
    assert (SYNTHETIC_DIR / FAMILY_FILES["B"]).is_file()
