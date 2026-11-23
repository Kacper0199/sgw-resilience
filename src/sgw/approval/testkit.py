"""Test helpers shared by `tests/unit/approval` and `tests/security`: a scratch database migrated with
`db/migrations`, and an OPA 1.22.4 server (from SGW_TEST_OPA_URL or an ad-hoc container on 8231-8239)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from sgw.approval.deps import SESSION_READER, SESSION_WRITER
from sgw.approval.opa_cli import OPA_IMAGE
from sgw.approval.policy import ApproveDecision, PolicyInput, ProposeDecision, ReferencePolicy
from sgw.approval.service import ApprovalService
from sgw.contracts import golden
from sgw.contracts.api_models import ApprovalRequest, ProposalCard, ProposalCreate
from sgw.contracts.vocab import ActionType

DB_ENV = "SGW_TEST_DATABASE_URL"
OPA_ENV = "SGW_TEST_OPA_URL"
EXTENSIONS = ("timescaledb", "postgis", "vector", "btree_gist", "pgcrypto")
GROUP_ROLES = ("sgw_app", "sgw_readonly")
OPA_PORTS = range(8231, 8240)


def admin_dsn() -> str | None:
    """SGW_TEST_DATABASE_URL, else the local stack's superuser DSN from `var/secrets` when it exists."""
    env = os.environ.get(DB_ENV)
    if env:
        return env
    try:
        from sgw.cli.support import load_credentials

        return load_credentials().admin_dsn()
    except Exception:  # noqa: BLE001
        return None


def _with_db(url: str, dbname: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{dbname}"


@contextmanager
def scratch_database(prefix: str = "sgw_wp09a_t") -> Iterator[str]:
    """A fresh database with every migration applied; yields a superuser DSN and drops it afterwards."""
    from sgw.common.migrate import apply

    admin = admin_dsn()
    if admin is None:
        raise RuntimeError(f"{DB_ENV} not set and no local stack credentials")
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(admin, autocommit=True) as conn:
        for role in GROUP_ROLES:
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                conn.execute(f"CREATE ROLE {role} NOLOGIN")
        conn.execute(f'CREATE DATABASE "{name}"')
    url = _with_db(admin, name)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for ext in EXTENSIONS:
                conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
        apply(url)
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _free_port() -> int | None:
    for port in OPA_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return None


def _wait_healthy(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    return False


@contextmanager
def opa_server() -> Iterator[str | None]:
    """Yields an OPA base URL, or None when neither SGW_TEST_OPA_URL nor docker is available."""
    env = os.environ.get(OPA_ENV)
    if env:
        yield env.rstrip("/")
        return
    docker = shutil.which("docker")
    if docker is None or subprocess.run([docker, "info"], capture_output=True, check=False).returncode != 0:  # noqa: S603
        yield None
        return
    started: str | None = None
    url: str | None = None
    for _ in range(3):
        port = _free_port()
        if port is None:
            break
        name = f"sgw-wp09a-opa-test-{uuid.uuid4().hex[:8]}"
        run = subprocess.run(  # noqa: S603
            [docker, "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{port}:8181", OPA_IMAGE]
            + ["run", "--server", "--addr=0.0.0.0:8181", "--disable-telemetry"],
            capture_output=True,
            check=False,
        )
        if run.returncode == 0:
            started, url = name, f"http://127.0.0.1:{port}"
            break
    try:
        yield url if url and _wait_healthy(url) else None
    finally:
        if started:
            subprocess.run([docker, "stop", started], capture_output=True, check=False)  # noqa: S603


@contextmanager
def seeded_database() -> Iterator[str]:
    """A scratch database with the K18 users and the Helene crew proposal (`sgw seed`)."""
    from sgw.approval.seed import run_seed

    with scratch_database() as url:
        run_seed(url, use_default_ledger=False)
        with psycopg.connect(url, autocommit=True) as conn:
            add_asset(conn, CLEAR_YARD, in_hazard_zone=False)
        yield url


class MutableClock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **delta: float) -> datetime:
        self.at = self.at + timedelta(**delta)
        return self.at


class PermissivePolicy:
    """Allows every proposal and decision, so tests can prove the database triggers hold on their own."""

    def __init__(self) -> None:
        self._reference = ReferencePolicy()

    def propose(self, payload: PolicyInput) -> ProposeDecision:
        found = self._reference.propose(payload)
        return ProposeDecision(allow=True, deny=(), classification=found.classification)

    def approve(self, payload: PolicyInput) -> ApproveDecision:
        return ApproveDecision(allow=True, deny=(), complete=False, remaining_functions=())


TEST_USER_HEADER = "X-Test-User"


@contextmanager
def api_client(dsn: str, service: ApprovalService) -> Iterator[tuple[TestClient, list[Any]]]:
    """The proposals router on a bare FastAPI app; the session is stubbed by the X-Test-User header."""
    from psycopg_pool import ConnectionPool

    from sgw.api.routers.proposals import router

    published: list[Any] = []
    app = FastAPI()
    app.include_router(router)
    app.state.approval_service = service
    app.state.publish_events = published.extend

    def header_user(x_test_user: Annotated[str | None, Header()] = None) -> str:
        if not x_test_user:
            raise HTTPException(status_code=401, detail="no session")
        return x_test_user

    app.dependency_overrides[SESSION_READER] = header_user
    app.dependency_overrides[SESSION_WRITER] = header_user
    with ConnectionPool(dsn, min_size=1, max_size=4, kwargs={"autocommit": True}, open=True) as pool:
        app.state.approval_db_pool = pool
        with TestClient(app) as client:
            yield client, published


YARDS = (golden.YARD_SANDHILL, golden.YARD_MILLPOND)


def crew_request(sandhill: int = 12, millpond: int = 8, **extra: int | str | bool) -> ProposalCreate:
    params: dict[str, int | str | bool | list[str]] = {
        f"crews_at_{golden.YARD_SANDHILL}": sandhill,
        f"crews_at_{golden.YARD_MILLPOND}": millpond,
        **extra,
    }
    return ProposalCreate(
        decision_case_id=golden.CASE_CREWS,
        action_type=ActionType.PREPOSITION_CREWS,
        params=params,
        target_ids=list(YARDS),
        evidence_ids=["EV-ADV-HELENE-N"],
    )


def new_crew_proposal(
    conn: psycopg.Connection[Any], svc: ApprovalService, sandhill: int = 12, millpond: int = 8
) -> ProposalCard:
    return svc.create(conn, proposed_by="ops_dm_01", request=crew_request(sandhill, millpond)).value


def approve_req(card: ProposalCard, decision: Literal["approve", "reject"] = "approve") -> ApprovalRequest:
    return ApprovalRequest(
        decision=decision, proposal_version=card.proposal_version, action_hash=card.action_hash
    )


def add_user(
    conn: psycopg.Connection[Any], user_id: str, functions: list[str], can_approve: bool = True
) -> None:
    conn.execute(
        "INSERT INTO app_user (user_id, display_name, persona, function, functions, can_approve)"
        " VALUES (%s, %s, 'T', %s, %s::sgw_approval_function[], %s) ON CONFLICT (user_id) DO NOTHING",
        (user_id, f"Test {user_id}", functions[0], functions, can_approve),
    )


def repo_token(conn: psycopg.Connection[Any], proposal_id: str) -> dict[str, Any] | None:
    from sgw.approval.repository import token_for

    return token_for(conn, proposal_id)


CLEAR_YARD = "STG-AIK-CLEARWATER-LOT"


def staging_request(customers: int = 400, target: str = CLEAR_YARD) -> ProposalCreate:
    """T2 small staging at a yard outside the hazard zone (`seeded_database` adds CLEAR_YARD)."""
    return ProposalCreate(
        decision_case_id=golden.CASE_CREWS,
        action_type=ActionType.STAGE_CREWS_SMALL,
        params={"crews": 2, "customers_affected": customers},
        target_ids=[target],
        evidence_ids=[],
    )


def service_for(engine: str, opa_url: str | None, clock: MutableClock) -> ApprovalService | None:
    """`reference`, `opa` (None when no OPA server) or `permissive` (database triggers only)."""
    from sgw.approval.policy import OpaPolicy, PolicyEngine

    policy: PolicyEngine
    if engine == "opa":
        if opa_url is None:
            return None
        opa = OpaPolicy(opa_url, allow_load=True)
        opa.load()
        policy = opa
    elif engine == "permissive":
        policy = PermissivePolicy()
    else:
        policy = ReferencePolicy()
    return ApprovalService(policy, scenario_clock=clock, token_clock=clock)


def add_asset(
    conn: psycopg.Connection[Any],
    asset_id: str,
    *,
    in_hazard_zone: bool | None = None,
    customers: int | None = 0,
    critical: bool = False,
) -> None:
    """A staging-site asset in Aiken; `None` leaves the hazard or customer fact missing."""
    attributes: dict[str, Any] = {"synthetic": True}
    if in_hazard_zone is not None:
        attributes["in_hazard_zone"] = in_hazard_zone
    if customers is not None:
        attributes["customers_source"] = "test"
    conn.execute(
        "INSERT INTO asset (asset_id, domain, kind, region_id, customers_served, critical_facility,"
        " attributes) VALUES (%s, 'electric', 'staging_yard', %s, %s, %s, %s)"
        " ON CONFLICT (asset_id) DO NOTHING",
        (asset_id, golden.REGION_AIKEN, customers or 0, critical, Jsonb(attributes)),
    )
