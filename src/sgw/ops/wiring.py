"""Production wiring of `ControlService`: WP-07 outbox for K2 events, WP-09b signed checkpoints after each
change and the WP-09b verifier as the restore's audit-chain check."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import psycopg

from sgw.approval import audit
from sgw.approval.ledger import OutboxSink
from sgw.approval.signer import SIGNING_ENV, AuditPaths, Keyring, active_signer, default_paths
from sgw.ops.control import ChainReport, ControlService, wall_clock
from sgw.ops.reconciler import FEED_PROBE_ENV


def notary_for(
    paths: AuditPaths, env: Mapping[str, str] | None = None
) -> Callable[[psycopg.Connection[Any]], None] | None:
    """None where the process holds no signing key by design (`SGW_AUDIT_SIGNING=0`, the stack's api):
    audit-checkpoint signs the change within its interval, as for break-glass."""
    if (os.environ if env is None else env).get(SIGNING_ENV, "1") == "0":
        return None

    def notarise(conn: psycopg.Connection[Any]) -> None:
        signer = active_signer(paths)
        if signer is not None:
            audit.checkpoint(conn, signer, audit.AnchorStore(paths.anchors))

    return notarise


def chain_check_for(paths: AuditPaths) -> Callable[[psycopg.Connection[Any]], ChainReport]:
    def check(conn: psycopg.Connection[Any]) -> ChainReport:
        keyring = Keyring.load(paths.keyring) if paths.keyring.is_file() else None
        anchors = audit.AnchorStore(paths.anchors) if paths.anchors.is_dir() else None
        return audit.verify(conn, keyring=keyring, anchors=anchors)

    return check


def build_service(
    *,
    clock: Callable[[], datetime] = wall_clock,
    scenario_clock: Callable[[], datetime] | None = None,
    env: Mapping[str, str] | None = None,
    paths: AuditPaths | None = None,
) -> ControlService:
    environ = dict(os.environ if env is None else env)
    audit_paths = paths or default_paths()
    return ControlService(
        clock=clock,
        scenario_clock=scenario_clock,
        ledger=OutboxSink(),
        notary=notary_for(audit_paths, environ),
        chain_check=chain_check_for(audit_paths),
        env=environ,
        feed_probe=environ.get(FEED_PROBE_ENV) == "1",
    )
