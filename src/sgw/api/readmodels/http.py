"""Shared response helpers for the read routes: a strong `ETag` over the JSON body with `If-None-Match` ->
304, `Cache-Control: private, max-age=<s>`, `Vary: Cookie`; an `X-SGW-Provenance` header for K3 shapes that
carry no provenance field; and the K12 span every read emits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from fastapi import Request, Response
from opentelemetry.trace import Span
from pydantic import BaseModel

from sgw.api.sessions import AuthUser
from sgw.common.telemetry import sgw_span
from sgw.contracts.api_models import Provenance
from sgw.contracts.base import utc_iso
from sgw.contracts.vocab import Classification, RunMode

DEFAULT_MAX_AGE_S = 30


def _dump(data: BaseModel | Sequence[BaseModel]) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    return [item.model_dump(mode="json") for item in data]


def provenance_header(p: Provenance) -> dict[str, str]:
    parts = [f"source={p.source}"]
    if p.model_id:
        parts.append(f"model_id={p.model_id}")
    if p.rule_id:
        parts.append(f"rule_id={p.rule_id}")
    if p.as_of is not None:
        parts.append(f"as_of={utc_iso(p.as_of)}")
    parts.append(f"label={p.label.value}")
    return {"X-SGW-Provenance": "; ".join(parts)}


def cached_json(
    request: Request,
    data: BaseModel | Sequence[BaseModel],
    *,
    headers: dict[str, str] | None = None,
    max_age_s: int = DEFAULT_MAX_AGE_S,
) -> Response:
    body = json.dumps(_dump(data), separators=(",", ":"), ensure_ascii=False).encode()
    tag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    common = {"ETag": tag, "Cache-Control": f"private, max-age={max_age_s}", "Vary": "Cookie"}
    common.update(headers or {})
    wanted = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
    if tag in wanted or "*" in wanted:
        return Response(status_code=304, headers=common)
    return Response(content=body, media_type="application/json", headers=common)


@contextmanager
def read_span(
    name: str, user: AuthUser, classification: Classification = Classification.C1
) -> Iterator[Span]:
    with sgw_span(
        f"api.read.{name}",
        run_id=None,
        classification=classification,
        user_role=user.role,
        run_mode=RunMode.REPLAY,
    ) as span:
        yield span
