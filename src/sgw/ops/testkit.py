"""Test helpers for the ops service and router: a seeded scratch database (WP-09a seed: K18 users and the
Helene crew proposal), a bare FastAPI app with the ops routers whose session is stubbed by headers, and an
in-memory audit signer so checkpoints can be asserted."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from sgw.approval import audit
from sgw.approval import testkit as approval_tk
from sgw.approval.deps import SESSION_READER
from sgw.approval.ledger import OutboxSink
from sgw.approval.signer import Ed25519Signer, Keyring
from sgw.contracts.vocab import KillLevel
from sgw.ops.control import ControlService, KillOutcome
from sgw.ops.errors import OpsError

TEST_USER_HEADER = "X-Test-User"
STEP_UP_HEADER = "X-Test-Step-Up"
admin_dsn = approval_tk.admin_dsn
TEST_SIGNER = Ed25519Signer.generate()


@contextmanager
def ops_database() -> Iterator[str]:
    with approval_tk.seeded_database() as url:
        yield url


@dataclass
class Notary:
    """Checkpoint after every change with a throwaway Ed25519 key; records the signed heads."""

    signer: Ed25519Signer = field(default_factory=lambda: TEST_SIGNER)
    signed: list[int] = field(default_factory=list)

    def __call__(self, conn: psycopg.Connection[Any]) -> None:
        made = audit.checkpoint(conn, self.signer, None)
        if made is not None:
            self.signed.append(made.seq)

    @property
    def keyring(self) -> Keyring:
        return Keyring().rotate(self.signer, datetime(2024, 1, 1, tzinfo=UTC))

    def chain_check(self, conn: psycopg.Connection[Any]) -> audit.VerifyReport:
        return audit.verify(conn, keyring=self.keyring)


def stepped_session(conn: psycopg.Connection[Any], user_id: str, *, step_up: bool = True) -> str:
    """A live session row for `user_id` (stepped up unless told otherwise); returns its token hash."""
    token_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    conn.execute(
        "INSERT INTO session (token_hash, user_id, expires_at, step_up_at)"
        " VALUES (%s, %s, now() + interval '1 hour', CASE WHEN %s THEN now() END)",
        (token_hash, user_id, step_up),
    )
    return token_hash


@dataclass
class SteppedUpService(ControlService):
    """Signs restores with a fresh stepped-up session of the signer unless the caller passes one."""

    auto_session: bool = True

    def set_kill(
        self,
        conn: psycopg.Connection[Any],
        *,
        user_id: str,
        level: KillLevel,
        reason: str,
        session_hash: str | None = None,
        stepped_up: bool = False,
    ) -> KillOutcome:
        if session_hash is None and self.auto_session:
            session_hash, stepped_up = stepped_session(conn, user_id), True
        return super().set_kill(
            conn,
            user_id=user_id,
            level=level,
            reason=reason,
            session_hash=session_hash,
            stepped_up=stepped_up,
        )


def service(env: dict[str, str] | None = None, *, notary: Notary | None = None) -> SteppedUpService:
    signer = notary or Notary()
    return SteppedUpService(ledger=OutboxSink(), notary=signer, chain_check=signer.chain_check, env=env or {})


def ops_app(dsn: str, svc: ControlService) -> Iterator[TestClient]:
    from psycopg_pool import ConnectionPool

    from sgw.api.routers.ops import Principal, ops_writer, proposed_router, router

    app = FastAPI()
    app.include_router(router)
    app.include_router(proposed_router)
    if isinstance(svc, SteppedUpService):
        svc.auto_session = False
    app.state.ops_control_service = svc

    def reader(x_test_user: Annotated[str | None, Header()] = None) -> str:
        if not x_test_user:
            raise HTTPException(status_code=401, detail="no session")
        return x_test_user

    def writer(
        x_test_user: Annotated[str | None, Header()] = None,
        x_test_step_up: Annotated[str | None, Header()] = None,
    ) -> Principal:
        user = reader(x_test_user)
        if x_test_step_up != "1":
            return Principal(user, False)
        with app.state.approval_db_pool.connection() as conn:
            return Principal(user, True, stepped_session(conn, user))

    app.dependency_overrides[SESSION_READER] = reader
    app.dependency_overrides[ops_writer] = writer
    with ConnectionPool(dsn, min_size=1, max_size=4, kwargs={"autocommit": True}, open=True) as pool:
        app.state.approval_db_pool = pool
        with TestClient(app) as client:
            yield client


@contextmanager
def client_for(dsn: str, svc: ControlService) -> Iterator[TestClient]:
    yield from ops_app(dsn, svc)


def h(user: str, *, step_up: bool = False) -> dict[str, str]:
    headers = {TEST_USER_HEADER: user}
    if step_up:
        headers[STEP_UP_HEADER] = "1"
    return headers


def audit_kinds(conn: psycopg.Connection[Any], since_seq: int = 0) -> list[str]:
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT kind FROM audit_event WHERE stream = 'global' AND seq > %s ORDER BY seq", (since_seq,)
        ).fetchall()
    ]


def audit_head(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute("SELECT coalesce(max(seq), 0) FROM audit_event WHERE stream = 'global'").fetchone()
    return int(row[0]) if row else 0


def ledger_types(conn: psycopg.Connection[Any], since_seq: int = 0) -> list[str]:
    return [
        str(r[0])
        for r in conn.execute(
            "SELECT type FROM event WHERE ledger_seq > %s ORDER BY ledger_seq", (since_seq,)
        ).fetchall()
    ]


def ledger_head(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute("SELECT coalesce(max(ledger_seq), 0) FROM event").fetchone()
    return int(row[0]) if row else 0


def reset_control(admin_url: str) -> None:
    """Back to K0/M0 with no signals, as the owner (bypassing the restore rule) between tests."""
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute("SET session_replication_role = replica")
        conn.execute("DELETE FROM ops_signal")
        conn.execute("UPDATE ops_kill_restore SET state = 'cancelled' WHERE state = 'pending'")
        conn.execute(
            "INSERT INTO control_state (id) VALUES (1) ON CONFLICT (id) DO UPDATE"
            " SET kill_level = 'K0', degraded_mode = 'M0', updated_by = '{}', updated_at = %s",
            (datetime.now(UTC),),
        )


def expect_error(error: OpsError, code: str) -> None:
    assert error.code == code, f"{error.code}: {error.message}"
