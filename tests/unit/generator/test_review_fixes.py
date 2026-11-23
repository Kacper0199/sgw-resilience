"""Hinge robustness, wind reach, quoted decide-by, family isolation."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from sgw.generator.config import FAMILY_FILES, SYNTHETIC_DIR, parse_utc
from sgw.generator.scenario import GenerationResult, generate
from sgw.generator.truth import Truth
from sgw.generator.wind import epoch


def _robustness(generated: GenerationResult) -> dict:
    return generated.truth_table["hinge_robustness"]


def test_shift_grows_monotonically_with_the_pinned_error_of_n(generated: GenerationResult) -> None:
    sweep = _robustness(generated)["pin_sweep"]
    scales = [r["scale"] for r in sweep]
    shifts = [r["shift_min"] for r in sweep]
    assert scales == sorted(scales) and scales[0] == 0.0
    assert shifts[0] == pytest.approx(0.0, abs=15.0)
    assert all(b <= a for a, b in zip(shifts, shifts[1:], strict=False))
    assert shifts[-1] < shifts[0] - 60.0
    shares = [r["N"]["share_ppm"] for r in sweep]
    assert all(b <= a for a, b in zip(shares, shares[1:], strict=False))


def test_verdict_flip_needs_a_pin_and_holds_over_a_threshold_band(generated: GenerationResult) -> None:
    rob = _robustness(generated)
    assert rob["pin_sweep"][0]["N"]["verdict"] == "act_now"
    assert 0.0 < rob["min_pin_scale_for_flip"] <= 1.0
    lo, hi = rob["flip_holds_for_member_p_loss"]
    assert lo <= 0.2 and hi >= 0.3


def test_absolute_decide_by_moves_later_with_a_higher_exposure_level(generated: GenerationResult) -> None:
    rows = _robustness(generated)["exposure_sensitivity"]
    times = [r["N+1"]["decide_by_utc"] for r in rows if r["N+1"]["decide_by_utc"]]
    assert times == sorted(times) and len(times) >= 3


def test_quoted_value_is_the_effective_decide_by(generated: GenerationResult) -> None:
    hinge = next(c for c in generated.truth_table["seeded_cases"] if c["id"] == "HINGE-PS17-N-N1")["outcome"]
    assert hinge["quoted"] == "effective"
    for adv in ("N", "N1"):
        assert hinge[f"effective_decide_by_{adv}_utc"] <= hinge[f"decide_by_{adv}_utc"]
    assert hinge["effective_decide_by_N1_utc"] < hinge["effective_decide_by_N_utc"]
    assert hinge["effective_shift_min"] < 0


def test_storm_wind_does_not_fail_assets_a_day_before_landfall(truth: Truth) -> None:
    early = np.sum(truth.fault_t < epoch(parse_utc("2024-09-26T18:00:00Z")))
    failed = np.sum(~np.isnan(truth.fault_t))
    assert early <= 0.01 * failed


def test_validation_fractions_are_consistent(generated: GenerationResult) -> None:
    with (SYNTHETIC_DIR / "validation" / "helene_eaglei_county.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        frac = float(r["peak_frac"])
        assert 0.0 <= frac <= 1.0
        denominator = max(float(r["total_customers"]), float(r["customers_mcc"]))
        assert int(r["frac_capped"]) == int(int(r["peak_out"]) > denominator)
    assert generated.truth_table["validation"]["county_peak_fraction"]["observed_capped_counties"] >= 0


def test_generate_never_reads_family_b(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: list[str] = []
    original = Path.read_text

    def spy(self: Path, *args: object, **kwargs: object) -> str:
        seen.append(self.name)
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", spy)
    generate("helene", tmp_path / "a")
    assert FAMILY_FILES["A"] in seen
    assert FAMILY_FILES["B"] not in seen
