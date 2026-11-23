"""Ranking and event-typing parameters: numbers.yaml first, the package YAML for proposed policy entries."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.common import numbers as numbers_mod

PARAMS_PATH = Path(__file__).with_name("ranking_params.yaml")


@cache
def params() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    return data


def critical_weights() -> dict[str, float]:
    weights = {k: float(v) for k, v in params()["critical_facility_weights"]["values"].items()}
    weights["hospital"] = float(numbers_mod.value("policy_ce_weight_hospital"))
    return weights


def equity_weight() -> float:
    return float(numbers_mod.value("policy_equity_weight"))
