"""K3 `reference`: regions and assets for the map. Read-only for any signed-in user, like the other
read routes; C0/C1 only (`sgw.reference.read`). Responses carry a strong `ETag` over the body and
`Cache-Control: private, max-age=60`; `If-None-Match` answers 304. The asset list pages by `asset_id`
with a `Link: <...>; rel="next"` header."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from sgw.api.deps import CurrentUser, DbConn, State
from sgw.api.errors import NotFound, Unprocessable
from sgw.api.routers._scenario import scenario_name
from sgw.contracts.api_models import Asset, Region
from sgw.contracts.vocab import Domain
from sgw.reference import read
from sgw.scenarios import packs

router = APIRouter(tags=["reference"])

CACHE_CONTROL = "private, max-age=60"
ASSET_CACHE_CONTROL = "private, no-cache"


def _cached(
    request: Request, items: list[BaseModel] | BaseModel, headers: dict[str, str] | None = None
) -> Response:
    data: Any = (
        [i.model_dump(mode="json") for i in items]
        if isinstance(items, list)
        else items.model_dump(mode="json")
    )
    body = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    tag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    common = {"ETag": tag, "Cache-Control": CACHE_CONTROL, "Vary": "Cookie", **(headers or {})}
    wanted = {t.strip().removeprefix("W/") for t in request.headers.get("if-none-match", "").split(",")}
    if tag in wanted or "*" in wanted:
        return Response(status_code=304, headers=common)
    return Response(content=body, media_type="application/json", headers=common)


@router.get("/api/regions", response_model=list[Region])
async def list_regions(request: Request, _: CurrentUser, conn: DbConn) -> Response:
    return _cached(request, list(await read.list_regions(conn)))


@router.get("/api/assets", response_model=list[Asset])
async def list_assets(
    request: Request,
    _: CurrentUser,
    conn: DbConn,
    state: State,
    bbox: Annotated[str | None, Query(max_length=200)] = None,
    domain: Annotated[Domain | None, Query()] = None,
    region: Annotated[list[str] | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query()] = read.DEFAULT_LIMIT,
    after: Annotated[str | None, Query(max_length=128)] = None,
) -> Response:
    try:
        query = read.AssetQuery(
            at=state.clock.now(),
            domain=domain,
            regions=read.region_ids(region),
            bbox=read.parse_bbox(bbox),
            limit=read.check_limit(limit),
            after=after or None,
        )
    except read.InvalidQuery as exc:
        raise Unprocessable(str(exc)) from exc
    page = await read.list_assets(conn, query)
    pack = packs.get(scenario_name(state))
    if pack is not None:
        own = pack.asset_ids
        return _cached(
            request, [a for a in page.items if a.asset_id in own], {"Cache-Control": ASSET_CACHE_CONTROL}
        )
    headers = {"Cache-Control": ASSET_CACHE_CONTROL}
    if page.next_after is not None:
        nxt = request.url.include_query_params(after=page.next_after)
        headers["Link"] = f'<{nxt.path}?{nxt.query}>; rel="next"'
    return _cached(request, list(page.items), headers)


@router.get("/api/assets/{asset_id}", response_model=Asset)
async def get_asset(asset_id: str, request: Request, _: CurrentUser, conn: DbConn, state: State) -> Response:
    found = await read.get_asset(conn, asset_id, state.clock.now())
    if found is None:
        raise NotFound("no such asset", code="ASSET_NOT_FOUND")
    return _cached(request, found, {"Cache-Control": ASSET_CACHE_CONTROL})
