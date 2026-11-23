from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from .sse_testkit import (
    DB_ENV,
    CaddyPorts,
    ScratchDb,
    create_scratch_db,
    docker_available,
    drop_scratch_db,
    require_free,
    start_api,
    start_caddy,
    stop_caddy,
    worker_ports,
)

NO_DB = f"{DB_ENV} not set: WP-08 integration tests not run"
NO_DOCKER = "Docker not running: SSE-through-Caddy tests not run"


@pytest.fixture(scope="session")
def scratch_db() -> Iterator[ScratchDb]:
    admin = os.environ.get(DB_ENV)
    if not admin:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs a database
    db = create_scratch_db(admin)
    try:
        yield db
    finally:
        drop_scratch_db(admin, db)


@pytest.fixture(scope="session")
def api_port(scratch_db: ScratchDb, tmp_path_factory: pytest.TempPathFactory) -> Iterator[int]:
    port = worker_ports()[0]
    require_free(port)
    log = tmp_path_factory.mktemp("api") / "uvicorn.log"
    proc = start_api(scratch_db, port, log)
    try:
        yield port
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def caddy(api_port: int, tmp_path_factory: pytest.TempPathFactory) -> Iterator[CaddyPorts]:
    if not docker_available():
        pytest.skip(NO_DOCKER)  # sgw-allow-skip: needs Docker
    _, site, relay = worker_ports()
    ports = start_caddy(api_port, Path(tmp_path_factory.mktemp("caddy")), site, relay)
    try:
        yield ports
    finally:
        stop_caddy(ports.name)
