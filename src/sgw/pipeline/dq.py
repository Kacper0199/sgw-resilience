"""Data-quality checks: Pandera schemas over ingest batches and observations, plus per-source freshness rules.
Each check becomes one `dq_check` row; `error` checks fail the run, `warn` checks are recorded and
published."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pandas as pd
import pandera.pandas as pa

from sgw.contracts.events import EnvelopeBase
from sgw.contracts.vocab import Classification, Quality
from sgw.pipeline.registry import CheckResult

FRESHNESS_LIMIT_S: dict[str, int] = {
    "nws-alerts": 900,
    "nhc-advisory-synthetic": 6 * 3600,
    "oms": 300,
    "ami-headend": 300,
    "scada-electric": 120,
    "scada-water": 30 * 60,
    "fsm-crews": 900,
    "eam": 3600,
    "lims": 24 * 3600,
    "gis-trace": 24 * 3600,
}
DEFAULT_FRESHNESS_LIMIT_S = 3600
REPORTS_ON_SCHEDULE = frozenset({"scada-water", "nhc-advisory-synthetic", "lims", "gis-trace"})
LATE_FACTOR = 2
REJECT_WARN_PPM = 10_000
REJECT_ERROR_PPM = 100_000


def freshness_limit(source_id: str) -> int:
    return FRESHNESS_LIMIT_S.get(source_id, DEFAULT_FRESHNESS_LIMIT_S)


def batch_frame(events: Sequence[EnvelopeBase]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_id": [e.source_id for e in events],
            "dedup_key": [e.dedup_key for e in events],
            "type": [e.type for e in events],
            "event_time": pd.to_datetime([e.event_time for e in events], utc=True),
            "known_at": pd.to_datetime([e.known_at for e in events], utc=True),
            "has_valid_at": [e.valid_at is not None for e in events],
            "classification": [e.classification.value for e in events],
            "coverage_ppm": pd.Series([e.coverage_ppm for e in events], dtype="int64"),
        }
    )


ENVELOPE_SCHEMA = pa.DataFrameSchema(
    {
        "source_id": pa.Column(str, pa.Check.str_length(1, 128)),
        "dedup_key": pa.Column(str, pa.Check.str_length(1, 256)),
        "type": pa.Column(str),
        "event_time": pa.Column(pd.DatetimeTZDtype(tz="UTC")),
        "known_at": pa.Column(pd.DatetimeTZDtype(tz="UTC")),
        "has_valid_at": pa.Column(bool),
        "classification": pa.Column(str, pa.Check.isin([c.value for c in Classification])),
        "coverage_ppm": pa.Column("int64", pa.Check.in_range(0, 1_000_000)),
    },
    checks=[
        pa.Check(
            lambda df: (df["known_at"] >= df["event_time"]) | df["has_valid_at"],
            name="known_at_not_before_event_time",
        )
    ],
    name="ingest_envelope",
    strict=True,
)

OBSERVATION_SCHEMA = pa.DataFrameSchema(
    {
        "source_id": pa.Column(str),
        "tag": pa.Column(str, pa.Check.str_length(1, 256)),
        "observed_at": pa.Column(pd.DatetimeTZDtype(tz="UTC")),
        "known_at": pa.Column(pd.DatetimeTZDtype(tz="UTC")),
        "value": pa.Column(float, pa.Check(lambda s: s.map(lambda v: v == v and abs(v) != float("inf")))),
        "unit": pa.Column(str, pa.Check.str_length(1, 32)),
        "quality": pa.Column(str, pa.Check.isin([q.value for q in Quality])),
    },
    unique=["source_id", "tag", "observed_at", "known_at"],
    name="observation",
    strict=True,
)


def schema_check(name: str, schema: pa.DataFrameSchema, frame: pd.DataFrame) -> CheckResult:
    if frame.empty:
        return CheckResult(name, "error", True, "0 rows")
    try:
        schema.validate(frame, lazy=True)
    except pa.errors.SchemaErrors as errors:
        cases = errors.failure_cases
        first = cases.iloc[0]
        return CheckResult(
            name,
            "error",
            False,
            f"{len(cases)} failure(s) in {len(frame)} rows; first: {first['column']} {first['check']}",
        )
    return CheckResult(name, "error", True, f"{len(frame)} rows valid")


def duplicate_check(frame: pd.DataFrame) -> CheckResult:
    repeats = int(frame["dedup_key"].duplicated().sum()) if not frame.empty else 0
    return CheckResult("ingest.duplicates_in_feed", "warn", repeats == 0, f"{repeats} repeated dedup_key(s)")


def out_of_order_check(frame: pd.DataFrame) -> CheckResult:
    regressions = 0
    if not frame.empty:
        for _, group in frame.groupby("source_id", sort=True):
            times = group["event_time"]
            regressions += int((times < times.cummax().shift(1)).sum())
    return CheckResult(
        "ingest.out_of_order", "warn", regressions == 0, f"{regressions} event_time regression(s)"
    )


def late_check(frame: pd.DataFrame) -> CheckResult:
    late = 0
    if not frame.empty:
        limits = frame["source_id"].map(lambda s: LATE_FACTOR * freshness_limit(s))
        delay = (frame["known_at"] - frame["event_time"]).dt.total_seconds()
        late = int((delay > limits).sum())
    return CheckResult(
        "ingest.late_arrivals",
        "warn",
        late == 0,
        f"{late} event(s) known later than {LATE_FACTOR}x freshness",
    )


def reject_checks(fetched: int, rejected: int) -> list[CheckResult]:
    total = fetched + rejected
    ppm = rejected * 1_000_000 // total if total else 0
    observed = f"{rejected} of {total} record(s) quarantined ({ppm} ppm)"
    return [
        CheckResult("ingest.quarantine_share_warn", "warn", ppm <= REJECT_WARN_PPM, observed),
        CheckResult("ingest.quarantine_share_error", "error", ppm <= REJECT_ERROR_PPM, observed),
    ]


def freshness_check(
    source_id: str, last_event_time: datetime | None, now: datetime, *, last_known_at: datetime | None = None
) -> CheckResult:
    """A feed that reports on a schedule is late when its newest data is older than the limit. A feed that
    reports only when something changes (alerts, outages, meters, devices, crews, asset records) is not late
    for being quiet; it is late when its newest data arrived more than the limit after it was measured."""
    limit = freshness_limit(source_id)
    name = f"freshness.{source_id}"
    if source_id in REPORTS_ON_SCHEDULE:
        if last_event_time is None:
            return CheckResult(name, "warn", False, "no data", limit)
        age = int((now - last_event_time).total_seconds())
        return CheckResult(name, "warn", age <= limit, f"product age {age} s", limit)
    if last_event_time is None or last_known_at is None:
        return CheckResult(name, "warn", True, "nothing reported yet", limit)
    lag = int((last_known_at - last_event_time).total_seconds())
    return CheckResult(name, "warn", lag <= limit, f"ingest lag {lag} s", limit)
