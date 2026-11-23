"""K17 eval report format: `evals/reports/<name>.json`, the only source of model numbers in deliverables."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from sgw.contracts.base import Contract, UtcDatetime
from sgw.contracts.vocab import EvalSplit, NumberLabel


class MetricRow(Contract):
    metric: str
    value: float
    unit: str
    n: int = Field(ge=1)
    split: EvalSplit
    label: NumberLabel
    baseline_name: str
    baseline_value: float
    threshold: float
    direction: Literal["higher_is_better", "lower_is_better"]
    passed: bool
    ci_low: float | None = None
    ci_high: float | None = None

    @model_validator(mode="after")
    def _pass_consistent(self) -> MetricRow:
        ok = (
            self.value >= self.threshold
            if self.direction == "higher_is_better"
            else self.value <= self.threshold
        )
        if ok != self.passed:
            raise ValueError(f"{self.metric}: passed={self.passed} disagrees with value vs threshold")
        if (self.ci_low is None) != (self.ci_high is None):
            raise ValueError("ci_low and ci_high come together")
        if (
            self.ci_low is not None
            and self.ci_high is not None
            and not self.ci_low <= self.value <= self.ci_high
        ):
            raise ValueError("value outside its interval")
        return self


class EvalReport(Contract):
    name: str
    schema_version: int = Field(default=1, ge=1)
    created_at: UtcDatetime
    code_version: str
    llm_mode: Literal["live", "record", "replay"]
    command: str = Field(description="exact command that reproduces the report")
    metrics: list[MetricRow] = Field(min_length=1)
