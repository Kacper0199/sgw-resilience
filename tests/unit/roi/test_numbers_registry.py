"""Every ROI value quoted through numbers.yaml equals the committed model output."""

from __future__ import annotations

import json

import pytest

from sgw.common.numbers import load
from sgw.roi.__main__ import RESULTS_PATH
from sgw.roi.registry import REGISTRY, lookup

RESULTS = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
NUMBERS = load().numbers


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_numbers_value_equals_roi_results(key: str) -> None:
    path, decimals, scale = REGISTRY[key]
    expected = round(lookup(RESULTS, path) * scale, decimals)
    assert key in NUMBERS, f"{key} missing from data/numbers/numbers.yaml"
    assert NUMBERS[key].value == pytest.approx(expected, abs=10 ** (-decimals) / 2), key


def test_derived_numbers_name_their_source() -> None:
    for key in REGISTRY:
        e = NUMBERS[key]
        if e.label.value == "C" and key.startswith(
            ("stage_one_", "gate_", "cost_", "benefit_", "roi_struct_")
        ):
            assert e.source.startswith("data/roi/"), key
