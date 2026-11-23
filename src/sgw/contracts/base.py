from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

PPM_SCALE = 1_000_000


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        ser_json_inf_nan="strings",
        use_enum_values=False,
        populate_by_name=True,
    )


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
Ppm = Annotated[int, Field(ge=0, le=PPM_SCALE, description="probability or share in parts per million")]
SchemaVersion = Annotated[int, Field(ge=1)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")]


def ppm_from_fraction(value: float) -> int:
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("probability must be finite")
    if not 0.0 <= value <= 1.0:
        raise ValueError("probability must be within [0, 1]")
    return round(value * PPM_SCALE)


def utc_iso(value: datetime) -> str:
    return (
        _require_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")
        if value.microsecond == 0
        else (_require_utc(value).isoformat().replace("+00:00", "Z"))
    )


def json_ready(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=False)
