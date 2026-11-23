"""V4-08: the stack's api holds no audit private key (`SGW_AUDIT_SIGNING=0`, audit-checkpoint signs), so a
control change does not try to sign; a database dropped under the API (demo moment load) is a lost
connection, not a conflicting change."""

from __future__ import annotations

from pathlib import Path

import psycopg
import psycopg.errors

from sgw.approval.signer import AuditPaths
from sgw.ops.errors import OpsConflict, OpsUnavailable, connection_lost, from_db_error
from sgw.ops.wiring import build_service, notary_for


def _paths(tmp_path: Path) -> AuditPaths:
    return AuditPaths(
        keyring=tmp_path / "keyring.json", key_dir=tmp_path / "keys", anchors=tmp_path / "anchors"
    )


def test_no_notary_where_signing_is_off(tmp_path: Path) -> None:
    assert notary_for(_paths(tmp_path), {"SGW_AUDIT_SIGNING": "0"}) is None
    assert build_service(env={"SGW_AUDIT_SIGNING": "0"}, paths=_paths(tmp_path)).notary is None


def test_notary_where_signing_is_on(tmp_path: Path) -> None:
    assert notary_for(_paths(tmp_path), {}) is not None
    assert build_service(env={}, paths=_paths(tmp_path)).notary is not None


def test_lost_connection_is_unavailable_not_conflict() -> None:
    dropped = psycopg.errors.AdminShutdown("terminating connection due to administrator command")
    assert connection_lost(dropped)
    assert isinstance(from_db_error(dropped), OpsUnavailable)
    assert isinstance(from_db_error(psycopg.OperationalError("server closed the connection")), OpsUnavailable)
    assert isinstance(from_db_error(psycopg.errors.UniqueViolation("duplicate")), OpsConflict)
