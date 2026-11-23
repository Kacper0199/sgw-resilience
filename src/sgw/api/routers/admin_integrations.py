"""K3 admin read routes: integrations (tokens metadata, webhook subscriptions, latest
deliveries; no secrets, no hashes, host only) and System metrics (in-app request counts and times of this API
process, plus the Grafana link only while the obs profile answers). Platform admin only; read-only."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from sgw.api.deps import DbConn
from sgw.api.metrics import ApiMetrics
from sgw.api.readmodels import integrations, obs
from sgw.api.readmodels.http import cached_json, read_span
from sgw.api.routers.admin import Admin
from sgw.contracts.api_models import AdminIntegrations, SystemMetricsLink
from sgw.contracts.vocab import Classification

router = APIRouter(tags=["admin"])


@router.get("/api/admin/integrations", response_model=AdminIntegrations)
async def get_admin_integrations(request: Request, user: Admin, conn: DbConn) -> Response:
    with read_span("admin.integrations", user):
        doc = await integrations.integrations(conn)
    return cached_json(request, doc, max_age_s=0)


@router.get("/api/admin/system", response_model=SystemMetricsLink)
async def get_system_metrics_link(request: Request, user: Admin) -> SystemMetricsLink:
    with read_span("admin.system", user, Classification.C0):
        link = await run_in_threadpool(obs.system_link)
    metrics = getattr(request.app.state, "api_metrics", None)
    return link.model_copy(update={"api": metrics.activity()}) if isinstance(metrics, ApiMetrics) else link
