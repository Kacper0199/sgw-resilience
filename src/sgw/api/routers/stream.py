"""K4 `GET /api/stream/ops`: ledger frames, state tiles and heartbeats as server-sent events (DC-18)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from sgw.api.deps import ApiState, State
from sgw.api.errors import Unauthenticated, Unavailable
from sgw.api.security import SESSION_COOKIE
from sgw.api.sessions import resolve, resolve_by_hash
from sgw.api.stream import LedgerBroadcaster, OpsStream

router = APIRouter(tags=["stream"])

SSE_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


class CountedStream(StreamingResponse):
    """Releases the stream slot however the response ends, even if the body was never iterated."""

    def __init__(self, broadcaster: LedgerBroadcaster, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._broadcaster = broadcaster

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._broadcaster.close_stream()


def _session_check(state: ApiState, session_hash: str, user_id: str):  # type: ignore[no-untyped-def]
    async def still_valid() -> bool:
        async with state.pool.connection() as conn:
            user = await resolve_by_hash(conn, session_hash, state.clock.wall.now())
        return user is not None and user.user_id == user_id

    return still_valid


@router.get("/api/stream/ops")
async def stream_ops(request: Request, state: State) -> StreamingResponse:
    async with state.pool.connection() as conn:
        user = await resolve(conn, request.cookies.get(SESSION_COOKIE), state.clock.wall.now())
    if user is None:
        raise Unauthenticated("sign in first")
    broadcaster = state.broadcaster
    if not broadcaster.try_open_stream(state.settings.max_stream_clients):
        raise Unavailable("too many open streams", code="STREAM_LIMIT")
    try:
        stream = OpsStream(
            broadcaster=broadcaster,
            scenario_now=state.clock.now,
            heartbeat_s=state.settings.heartbeat_s,
            wall_now=state.clock.wall.now,
            still_valid=_session_check(state, user.session_hash, user.user_id),
        )
        return CountedStream(
            broadcaster,
            stream.frames(request.headers.get("last-event-id")),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    except BaseException:
        broadcaster.close_stream()
        raise
