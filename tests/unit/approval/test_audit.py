"""Audit chain: writer, signed checkpoints with anchors, verifier, key rotation."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from sgw.approval import audit
from sgw.approval import audit_testkit as at
from sgw.approval.signer import AuditPaths, Ed25519Signer, Keyring, SignerError, active_signer, generate_key

T0 = datetime(2024, 9, 26, 9, 0, tzinfo=UTC)


@pytest.fixture
def signer() -> Ed25519Signer:
    return Ed25519Signer.generate()


@pytest.fixture
def keyring(signer: Ed25519Signer) -> Keyring:
    return Keyring().rotate(signer, T0 - timedelta(days=1))


@pytest.fixture
def anchors(tmp_path: Path) -> audit.AnchorStore:
    return audit.AnchorStore(tmp_path / "anchors")


def test_chain_links_and_verifies_unsigned(conn: psycopg.Connection[Any]) -> None:
    stream = at.new_stream()
    recs = at.fill(conn, stream, 5, T0)
    assert [r.seq for r in recs] == [1, 2, 3, 4, 5]
    report = audit.verify(conn, stream=stream)
    assert report.ok and report.checked_to_seq == 5 and report.first_bad_seq is None
    assert report.result().notary == "UNSIGNED" and report.signed_head_seq is None


def test_checkpoint_signs_head_writes_anchor_and_is_idempotent(
    conn: psycopg.Connection[Any], signer: Ed25519Signer, keyring: Keyring, anchors: audit.AnchorStore
) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 4, T0)
    cp = audit.checkpoint(conn, signer, anchors, stream=stream, at=T0 + timedelta(minutes=1))
    assert cp is not None and cp.seq == 4 and cp.from_seq == 1 and cp.anchor_path is not None
    assert audit.checkpoint(conn, signer, anchors, stream=stream) is None
    at.fill(conn, stream, 2, T0 + timedelta(minutes=2))
    cp2 = audit.checkpoint(conn, signer, anchors, stream=stream, at=T0 + timedelta(minutes=3))
    assert cp2 is not None and (cp2.from_seq, cp2.seq) == (5, 6)
    report = audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors)
    assert report.ok, report.problems
    assert report.signed_head_seq == 6 and report.result().notary == "signed"
    with pytest.raises(FileExistsError):
        anchors.write(conn.info.dbname, {"stream": stream, "seq": 6})


def test_payload_edit_without_recompute_reports_that_seq(conn: psycopg.Connection[Any], db_url: str) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 6, T0)
    at.tamper(db_url, stream, 3, {"i": 3, "note": "edited"}, recompute_chain=False)
    report = audit.verify(conn, stream=stream)
    assert not report.ok and report.first_bad_seq == 3 and report.checked_to_seq == 2


def test_reorder_reports_first_bad_seq(conn: psycopg.Connection[Any], db_url: str) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 6, T0)
    at.swap(db_url, stream, 4, 5)
    report = audit.verify(conn, stream=stream)
    assert report.first_bad_seq == 4


def test_gap_reports_missing_seq(conn: psycopg.Connection[Any], db_url: str) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 5, T0)
    with psycopg.connect(db_url, autocommit=True) as admin, admin.transaction():
        admin.execute("SET session_replication_role = replica")
        admin.execute("DELETE FROM audit_event WHERE stream = %s AND seq = 2", (stream,))
    assert audit.verify(conn, stream=stream).first_bad_seq == 2


def test_forged_checkpoint_and_unknown_key_fail(
    conn: psycopg.Connection[Any], signer: Ed25519Signer, anchors: audit.AnchorStore
) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 3, T0)
    audit.checkpoint(conn, Ed25519Signer.generate(), anchors, stream=stream, at=T0 + timedelta(minutes=1))
    trusted = Keyring().rotate(signer, T0 - timedelta(days=1))
    report = audit.verify(conn, stream=stream, keyring=trusted, anchors=anchors)
    assert not report.ok and report.signed_head_seq is None
    assert any("signature does not verify" in p for p in report.problems)


def test_rotation_keeps_old_checkpoints_valid_and_bounds_the_retired_key(
    conn: psycopg.Connection[Any], anchors: audit.AnchorStore
) -> None:
    stream = at.new_stream()
    old, new = Ed25519Signer.generate(), Ed25519Signer.generate()
    ring = Keyring().rotate(old, T0 - timedelta(days=1))
    at.fill(conn, stream, 2, T0)
    audit.checkpoint(conn, old, anchors, stream=stream, at=T0 + timedelta(minutes=1))
    ring = ring.rotate(new, T0 + timedelta(minutes=5))
    assert ring.active == new.key_id and ring.get(old.key_id).retired_at is not None  # type: ignore[union-attr]
    at.fill(conn, stream, 2, T0 + timedelta(minutes=6))
    audit.checkpoint(conn, new, anchors, stream=stream, at=T0 + timedelta(minutes=7))
    assert audit.verify(conn, stream=stream, keyring=ring, anchors=anchors).ok
    at.fill(conn, stream, 1, T0 + timedelta(minutes=8))
    audit.checkpoint(conn, old, None, stream=stream, at=T0 + timedelta(minutes=9))
    late = audit.verify(conn, stream=stream, keyring=ring, anchors=anchors)
    assert not late.ok and any("checkpoint 5" in p for p in late.problems)


async def test_api_writer_rows_verify_with_this_verifier(db_url: str, conn: psycopg.Connection[Any]) -> None:
    from sgw.api import audit_log

    stream = at.new_stream()
    async with await psycopg.AsyncConnection.connect(db_url, autocommit=True) as aconn:
        for i in range(3):
            async with aconn.transaction():
                await audit_log.append(
                    aconn,
                    kind="persona_switched",
                    actor_type="user",
                    actor_id="ic_01",
                    subject="session",
                    payload={"i": i},
                    occurred_at=T0 + timedelta(seconds=i, microseconds=123),
                    stream=stream,
                )
    at.fill(conn, stream, 2, T0 + timedelta(minutes=1))
    report = audit.verify(conn, stream=stream)
    assert report.ok and report.checked_to_seq == 5


def test_list_events_pages_from_seq(conn: psycopg.Connection[Any]) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 5, T0)
    page = audit.list_events(conn, from_seq=3, limit=2, stream=stream)
    assert [e.seq for e in page] == [3, 4]
    assert page[1].prev_hash == page[0].hash


def test_runtime_role_cannot_rewrite_audit_or_checkpoints(conn: psycopg.Connection[Any]) -> None:
    stream = at.new_stream()
    at.fill(conn, stream, 1, T0)
    with conn.transaction():
        conn.execute("SET LOCAL ROLE sgw_app")
        for stmt in (
            "UPDATE audit_event SET kind = 'x' WHERE stream = %s",
            "DELETE FROM audit_checkpoint WHERE stream = %s",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(stmt, (stream,))


def test_keygen_writes_a_private_0600_key_outside_the_keyring(tmp_path: Path) -> None:
    paths = AuditPaths(
        keyring=tmp_path / "audit" / "keyring.json", key_dir=tmp_path / "secrets", anchors=tmp_path / "a"
    )
    first = generate_key(paths, T0)
    pem = paths.private_key(first.key_id)
    assert pem.is_file()
    if os.name != "nt":
        assert stat.S_IMODE(pem.stat().st_mode) == 0o600
    assert "PRIVATE" not in paths.keyring.read_text(encoding="utf-8")
    second = generate_key(paths, T0 + timedelta(days=1))
    ring = Keyring.load(paths.keyring)
    assert ring.active == second.key_id and len(ring.keys) == 2
    loaded = active_signer(paths)
    assert loaded is not None and loaded.key_id == second.key_id
    with pytest.raises(FileExistsError):
        second.write_pem(pem.with_name(paths.private_key(second.key_id).name))


def test_keyring_entry_must_match_its_public_key(signer: Ed25519Signer) -> None:
    raw = Keyring().rotate(signer, T0).to_json()
    raw["keys"][0]["public_key"] = Ed25519Signer.generate().public_key_hex
    with pytest.raises(SignerError):
        Keyring.from_json(raw)


def test_anchor_failure_after_commit_is_retried_and_never_a_false_alarm(
    conn: psycopg.Connection[Any],
    signer: Ed25519Signer,
    keyring: Keyring,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = at.new_stream()
    anchors = audit.AnchorStore(tmp_path / "anchors")
    at.fill(conn, stream, 3, T0)

    def broken(namespace: str, doc: dict[str, Any]) -> Path:
        raise OSError("anchors volume full")

    monkeypatch.setattr(anchors, "write", broken)
    cp = audit.checkpoint(conn, signer, anchors, stream=stream, at=T0 + timedelta(minutes=1))
    assert cp is not None and cp.anchor_path is None
    committed = conn.execute(
        "SELECT count(*) FROM audit_checkpoint WHERE stream = %s AND seq = 3", (stream,)
    ).fetchone()
    assert committed == (1,)
    report = audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors)
    assert report.ok and report.signed_head_seq == 3, report.problems
    monkeypatch.undo()
    at.fill(conn, stream, 2, T0 + timedelta(minutes=2))
    audit.checkpoint(conn, signer, anchors, stream=stream, at=T0 + timedelta(minutes=3))
    files = sorted(p.name for p in anchors.path(conn.info.dbname, stream, 1).parent.glob("*.json"))
    assert files == ["000000000003.json", "000000000005.json"]
    assert audit.verify(conn, stream=stream, keyring=keyring, anchors=anchors).ok


def test_retired_key_cannot_backdate_a_checkpoint_past_its_successor(
    conn: psycopg.Connection[Any], anchors: audit.AnchorStore
) -> None:
    stream = at.new_stream()
    old, new = Ed25519Signer.generate(), Ed25519Signer.generate()
    ring = Keyring().rotate(old, T0 - timedelta(days=1)).rotate(new, T0 + timedelta(minutes=5))
    at.fill(conn, stream, 2, T0)
    audit.checkpoint(conn, old, anchors, stream=stream, at=T0 + timedelta(minutes=1))
    at.fill(conn, stream, 2, T0 + timedelta(minutes=6))
    audit.checkpoint(conn, new, anchors, stream=stream, at=T0 + timedelta(minutes=7))
    at.fill(conn, stream, 2, T0 + timedelta(minutes=8))
    audit.checkpoint(conn, old, None, stream=stream, at=T0 + timedelta(minutes=2))
    report = audit.verify(conn, stream=stream, keyring=ring, anchors=anchors)
    assert not report.ok and report.signed_head_seq == 4
    assert any("checkpoint 6" in p and "retired key" in p for p in report.problems)


def test_pinned_active_key_must_match_the_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = AuditPaths(keyring=tmp_path / "k.json", key_dir=tmp_path / "s", anchors=tmp_path / "a")
    signer = generate_key(paths, T0)
    monkeypatch.setenv("SGW_AUDIT_ACTIVE_KEY", signer.key_id)
    assert active_signer(paths) is not None
    monkeypatch.setenv("SGW_AUDIT_ACTIVE_KEY", "ed25519:0000000000000000")
    with pytest.raises(SignerError):
        active_signer(paths)
