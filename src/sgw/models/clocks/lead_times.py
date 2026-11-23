"""Lead-time registry: every action lead time carries its rule id, version and SOP citation (K16 basis)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml
from pydantic import Field

from sgw.contracts.base import Contract
from sgw.contracts.clocks import ClockBasis
from sgw.contracts.vocab import ClockKind

LEAD_TIMES_PATH = Path(__file__).with_name("lead_times.yaml")


class LeadTime(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    minutes: int = Field(ge=0, le=60 * 24 * 14)
    sop: str
    source: str
    version: str

    @property
    def basis(self) -> ClockBasis:
        return ClockBasis(
            kind=ClockKind.MODEL_ESTIMATE,
            basis_id=f"lead_time.{self.key}",
            basis_version=self.version,
            citation=self.sop,
        )


def load(path: Path = LEAD_TIMES_PATH) -> dict[str, LeadTime]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    version = str(raw["version"])
    return {k: LeadTime(key=k, version=version, **v) for k, v in raw["lead_times"].items()}


@cache
def policy_value(key: str) -> float:
    raw = yaml.safe_load(LEAD_TIMES_PATH.read_text(encoding="utf-8"))
    try:
        return float(raw["policy"][key]["value"])
    except KeyError as exc:
        raise KeyError(f"no clock policy parameter {key!r}") from exc


@cache
def registry() -> dict[str, LeadTime]:
    return load()


def lead_time(key: str) -> LeadTime:
    try:
        return registry()[key]
    except KeyError as exc:
        raise KeyError(f"no lead time registered for action {key!r}") from exc
