"""K3 `healthz` (process alive) and `readyz` (database reachable, ledger tail running)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from sgw.api.deps import State
from sgw.contracts.api_models import Health

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    return Health(status="ok", checks={"process": "ok"})


@router.get("/readyz", response_model=Health)
async def readyz(state: State) -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with state.pool.connection(timeout=2) as conn:
            await conn.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = type(exc).__name__
    task = state.broadcaster._task
    checks["ledger_tail"] = "ok" if task is not None and not task.done() else "stopped"
    ok = all(v == "ok" for v in checks.values())
    body = Health(status="ok" if ok else "down", checks=checks)
    return JSONResponse(status_code=200 if ok else 503, content=body.model_dump(mode="json"))
