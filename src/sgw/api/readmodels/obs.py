"""System metrics link: Grafana is linked only while the optional `obs` profile answers.

The probe asks Grafana's `/api/health` (`SGW_OBS_GRAFANA_HEALTH_URL`; default the host port of the profile,
so an API in a container needs the compose service URL) with a short timeout and keeps the answer for
`CACHE_S` seconds. The link the browser opens is `SGW_OBS_GRAFANA_URL` (default the SGW dashboards folder)."""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime

import httpx

from sgw.contracts.api_models import SystemMetricsLink

HEALTH_ENV = "SGW_OBS_GRAFANA_HEALTH_URL"
LINK_ENV = "SGW_OBS_GRAFANA_URL"
GRAFANA_URL = "http://127.0.0.1:3001"
DEFAULT_LINK = f"{GRAFANA_URL}/dashboards/f/sgw-platform/"
DEFAULT_HEALTH = f"{GRAFANA_URL}/api/health"
HOW_TO_ENABLE = "Start the optional monitoring profile: `uv run sgw obs init`, then `uv run sgw obs up`."
TIMEOUT_S = 1.0
CACHE_S = 30.0

_lock = threading.Lock()
_cache: dict[str, tuple[float, bool]] = {}


def _probe(url: str) -> bool:
    try:
        r = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=False)
    except httpx.HTTPError:
        return False
    return r.status_code == 200


def grafana_up(url: str, now: float | None = None) -> bool:
    t = time.monotonic() if now is None else now
    with _lock:
        hit = _cache.get(url)
        if hit is not None and t - hit[0] < CACHE_S:
            return hit[1]
    up = _probe(url)
    with _lock:
        _cache[url] = (t, up)
    return up


def system_link(env: dict[str, str] | None = None) -> SystemMetricsLink:
    source = os.environ if env is None else env
    up = grafana_up(source.get(HEALTH_ENV) or DEFAULT_HEALTH)
    return SystemMetricsLink(
        obs_profile_up=up,
        grafana_url=(source.get(LINK_ENV) or DEFAULT_LINK) if up else None,
        checked_at=datetime.now(UTC).replace(microsecond=0),
        how_to_enable=HOW_TO_ENABLE,
    )
