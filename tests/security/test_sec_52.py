"""SEC-52 (STM 6.4): a superuser edits an audit row and recomputes every later hash. The signed checkpoints
and the anchored segments must expose it, and the verifier must name the first bad sequence. SEC-53 (newest
rows deleted) and SEC-54 (reorder) are checked alongside, and the verify endpoint is exercised over HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from sgw.approval import audit
from sgw.approval import audit_testkit as at
from sgw.approval import testkit as tk
from sgw.approval.signer import AuditPaths, Ed25519Signer, Keyring

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
T0 = datetime(2024, 9, 26, 9, 0, tzinfo=UTC)
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database("sgw_wp09b_t") as url:
        yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(db_url, autocommit=True) as c:
        yield c


@pytest.fixture
def signer() -> Ed25519Signer:
    return Ed25519Signer.generate()


@pytest.fixture
def keyring(signer: Ed25519Signer) -> Keyring:
    return Keyring().rotate(signer, EPOCH)


@pytest.fixture
def anchors(tmp_path: Path) -> audit.AnchorStore:
    return audit.AnchorStore(tmp_path / "anchors")


def _chain_with_checkpoints(
    conn: psycopg.Connection[Any], signer: Ed25519Signer, anchors: audit.AnchorStore | None
) -> str:
    """20 rows, checkpoints after 8 and 16, 4 unsigned rows at the head."""
    stream = at.new_stream()
    at.fill(conn, stream, 8, T0)
    audit.checkpoint(conn, signer, anchors, stream=stream, at=T0 + timedelta(minutes=10))
    at.fill(conn, stream, 8, T0 + timedelta(minutes=11))
    audit.checkpoint(conn, signer, anchors, stream=stream, at=T0 + timedelta(minutes=20))
    at.fill(conn, stream, 4, T0 + timedelta(minutes=21))
    return stream


@pytest.mark.parametrize("seq", [3, 8, 11])
def test_sec_52_rewrite_with_recomputed_hashes_reports_the_edited_seq(
    conn: psycopg.Connection[Any],
    db_url: str,
    signer: Ed25519Signer,
    keyring: Keyring,
    anchors: audit.AnchorStore,
    seq: int,
) -> None:
    stream = _chain_with_checkpoints(conn, signer, anchors)
    assert audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors).ok
    at.tamper(db_url, stream, seq, {"i": seq, "note": "approved by someone else"}, recompute_chain=True)
    chain_only = audit.verify(conn, stream=stream)
    assert chain_only.first_bad_seq is None and chain_only.checked_to_seq == 20, (
        "consistent without the notary"
    )
    report = audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors)
    assert not report.ok
    assert report.first_bad_seq == seq
    assert report.checked_to_seq == seq - 1
    assert report.signed_head_seq == (8 if seq > 8 else None)


def test_sec_52_without_anchors_fails_at_the_first_changed_checkpoint(
    conn: psycopg.Connection[Any], db_url: str, signer: Ed25519Signer, keyring: Keyring
) -> None:
    stream = _chain_with_checkpoints(conn, signer, None)
    at.tamper(db_url, stream, 11, {"i": 11, "note": "edited"}, recompute_chain=True)
    report = audit.verify(conn, stream=stream, keyring=keyring)
    assert not report.ok and report.first_bad_seq == 16 and report.signed_head_seq == 8


def test_sec_52_attacker_cannot_re_sign_the_checkpoint(
    conn: psycopg.Connection[Any],
    db_url: str,
    signer: Ed25519Signer,
    keyring: Keyring,
    anchors: audit.AnchorStore,
) -> None:
    stream = _chain_with_checkpoints(conn, signer, anchors)
    at.tamper(db_url, stream, 18, {"i": 18, "note": "edited"}, recompute_chain=True)
    audit.checkpoint(conn, Ed25519Signer.generate(), None, stream=stream, at=T0 + timedelta(minutes=30))
    report = audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors)
    assert not report.ok and report.signed_head_seq == 16
    assert any("checkpoint 20" in p for p in report.problems)


def test_sec_53_deleting_the_newest_rows_is_reported(
    conn: psycopg.Connection[Any],
    db_url: str,
    signer: Ed25519Signer,
    keyring: Keyring,
    anchors: audit.AnchorStore,
) -> None:
    stream = _chain_with_checkpoints(conn, signer, anchors)
    at.delete_from(db_url, stream, 14, checkpoints=True)
    report = audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors)
    assert not report.ok and report.first_bad_seq == 14 and report.checked_to_seq == 13


def test_sec_54_reorder_reports_the_first_bad_seq(
    conn: psycopg.Connection[Any],
    db_url: str,
    signer: Ed25519Signer,
    keyring: Keyring,
    anchors: audit.AnchorStore,
) -> None:
    stream = _chain_with_checkpoints(conn, signer, anchors)
    at.swap(db_url, stream, 5, 6)
    assert audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors).first_bad_seq == 5


def test_sec_52_verify_endpoint_reports_the_first_bad_seq(
    db_url: str, signer: Ed25519Signer, keyring: Keyring, tmp_path: Path
) -> None:
    from psycopg_pool import ConnectionPool

    from sgw.api.routers.audit import router
    from sgw.approval.breakglass_deps import SESSION_CSRF

    paths = AuditPaths(
        keyring=tmp_path / "keyring.json", key_dir=tmp_path / "keys", anchors=tmp_path / "anchors"
    )
    keyring.save(paths.keyring)
    anchors = audit.AnchorStore(paths.anchors)
    with psycopg.connect(db_url, autocommit=True) as conn:
        at.fill(conn, audit.STREAM, 6, T0)
        audit.checkpoint(conn, signer, anchors, at=T0 + timedelta(minutes=5))
        head = conn.execute("SELECT max(seq) FROM audit_event WHERE stream = 'global'").fetchone()
    assert head is not None
    target = int(head[0]) - 2
    app = FastAPI()
    app.include_router(router)
    app.state.audit_paths = paths
    app.state.audit_verify_window_s = 0

    def header_user(x_test_user: str | None = Header(default=None)) -> str:
        if not x_test_user:
            raise HTTPException(status_code=401, detail="no session")
        return x_test_user

    app.dependency_overrides[SESSION_CSRF] = header_user
    with ConnectionPool(db_url, min_size=1, max_size=2, kwargs={"autocommit": True}, open=True) as pool:
        app.state.approval_db_pool = pool
        with TestClient(app) as client:
            assert client.post("/api/audit/verify").status_code == 401
            good = client.post("/api/audit/verify", headers={"X-Test-User": "audit_01"}).json()
            assert good == {
                "ok": True,
                "checked_to_seq": target + 2,
                "first_bad_seq": None,
                "signed_head_seq": target + 2,
                "notary": "signed",
            }
            at.tamper(db_url, audit.STREAM, target, {"i": 0, "note": "edited"}, recompute_chain=True)
            bad = client.post("/api/audit/verify", headers={"X-Test-User": "audit_01"}).json()
            assert bad["ok"] is False and bad["first_bad_seq"] == target
            assert bad["checked_to_seq"] == target - 1 and bad["signed_head_seq"] is None
