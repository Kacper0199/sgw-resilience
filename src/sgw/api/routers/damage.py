"""CV damage triage: `GET /api/damage/queue` (photos in queue order with scores, seeded cases with
their tier), `GET /api/damage/thumbs/{image_id}` (the 240 px thumbnail of a queued photo),
`GET /api/damage/photos/{image_id}` (one photo for the preview: scores per label, licence) and
`GET /api/damage/images/{image_id}` (the full-size photo downloaded to this machine, else the thumbnail).
Files are looked up by image id in the queue and the sample, never by a client path."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response

from sgw.api.deps import CurrentUser
from sgw.api.errors import NotFound
from sgw.api.routers._cache import cached_json, etag_for, not_modified
from sgw.contracts.api_models import DamageLabelScore, DamagePhotoDetail, DamageQueue
from sgw.models.cv import images, read

router = APIRouter(tags=["ops"])
STATIC = "private, max-age=300"
THUMB_CACHE = "private, max-age=86400, immutable"
IMAGE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
IMAGE_CACHE = "private, max-age=3600"


def _queued(image_id: str) -> dict[str, Any]:
    row = read.queue_row(image_id) if IMAGE_ID.fullmatch(image_id) else None
    if row is None:
        raise NotFound("no queued photo with this id", code="PHOTO_NOT_FOUND")
    return row


@router.get("/api/damage/queue", operation_id="getDamageQueue", response_model=DamageQueue)
async def get_damage_queue(
    request: Request,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=read.MAX_LIMIT)] = read.DEFAULT_LIMIT,
) -> Response:
    return cached_json(request, read.damage_queue(limit), STATIC)


@router.get("/api/damage/thumbs/{image_id}", operation_id="getDamageThumb")
async def get_damage_thumb(image_id: str, request: Request, _: CurrentUser) -> Response:
    path = read.thumb_path(image_id) if IMAGE_ID.fullmatch(image_id) else None
    if path is None:
        raise NotFound("no thumbnail for this image", code="THUMB_NOT_FOUND")
    body = path.read_bytes()
    tag = etag_for(body)
    headers = {"ETag": tag, "Cache-Control": THUMB_CACHE, "X-Content-Type-Options": "nosniff"}
    if not_modified(request, tag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="image/jpeg", headers=headers)


@router.get("/api/damage/photos/{image_id}", operation_id="getDamagePhoto", response_model=DamagePhotoDetail)
async def get_damage_photo(image_id: str, request: Request, _: CurrentUser) -> Response:
    row = _queued(image_id)
    meta = images.sample_meta()
    detail = DamagePhotoDetail(
        image_id=image_id,
        rank=int(row["rank"]),
        triage_score=float(row["triage_score"]),
        signals=list(row.get("signals") or []),
        labels=[DamageLabelScore(label=k, score=v) for k, v in images.label_scores(image_id)],
        suggested_actions=list(row.get("suggested_actions") or []),
        human_only=list(row.get("human_only") or []),
        seeded_case_id=row.get("seeded_case_id"),
        status=str(row["status"]),
        image_url=images.IMAGE_ROUTE.format(image_id=image_id),
        full_size=images.image_path(image_id) is not None,
        dataset=meta["dataset"],
        licence=meta["licence"],
        model_id=read.queue_model(),
    )
    return cached_json(request, detail)


@router.get("/api/damage/images/{image_id}", operation_id="getDamageImage")
async def get_damage_image(image_id: str, request: Request, _: CurrentUser) -> Response:
    _queued(image_id)
    full = images.image_path(image_id)
    path = full or read.thumb_path(image_id)
    if path is None:
        raise NotFound("no image for this photo", code="IMAGE_NOT_FOUND")
    body = path.read_bytes()
    tag = etag_for(body)
    headers = {
        "ETag": tag,
        "Cache-Control": IMAGE_CACHE,
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
        "X-SGW-Image": "full" if full else "thumbnail",
    }
    if not_modified(request, tag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="image/jpeg", headers=headers)
