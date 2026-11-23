"""Strong ETag responses for read routes (the BE-UI1 pattern): the tag is a hash of the JSON body, a matching
`If-None-Match` answers 304. Scenario-time reads use `private, no-cache` so a clock seek is never hidden by
a cached copy; static artefacts may set a max-age. Not a router module (leading underscore)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from fastapi import Request, Response
from pydantic import BaseModel

REVALIDATE = "private, no-cache"


def etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


def not_modified(request: Request, tag: str) -> bool:
    wanted = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
    return tag in wanted or "*" in wanted


def cached_json(
    request: Request,
    payload: BaseModel | Sequence[BaseModel] | dict[str, Any],
    cache_control: str = REVALIDATE,
) -> Response:
    data: Any
    if isinstance(payload, Sequence):
        data = [i.model_dump(mode="json") for i in payload]
    elif isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    tag = etag_for(body)
    headers = {"ETag": tag, "Cache-Control": cache_control, "Vary": "Cookie"}
    if not_modified(request, tag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)
