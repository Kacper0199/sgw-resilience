from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sgw.cli.support import DB_NAME, DB_RUNTIME, CliError, read_env_file, secrets_dir, var_dir

CONTAINER_UID = 10001
CONTAINER_GID = 10001


@dataclass(frozen=True)
class AuditSetup:
    active_key: str
    created: bool
    keyring: Path
    key_dir: Path
    anchors: Path


def audit_dirs() -> tuple[Path, Path, Path]:
    """Host paths bind-mounted into api and audit-checkpoint (compose uses the same layout under var/)."""
    return var_dir() / "audit" / "keyring.json", secrets_dir() / "audit", var_dir() / "audit" / "anchors"


def run_ids() -> tuple[int, int]:
    """uid:gid the audit-writing containers run as.

    Docker Desktop (macOS, Windows) maps bind-mount ownership, so the image user 10001 can use host files.
    A Linux engine enforces host ownership: run as the invoking user so 0600 keys and the anchors dir work
    without chmod 777; when bootstrap runs as root, keep 10001 and hand the audit dirs to it instead."""
    if not sys.platform.startswith("linux"):
        return CONTAINER_UID, CONTAINER_GID
    uid, gid = os.getuid(), os.getgid()  # type: ignore[attr-defined,unused-ignore]
    if uid == 0:
        return CONTAINER_UID, CONTAINER_GID
    return uid, gid


def hand_to_containers(path: Path) -> None:
    """A host dir the containers write (gateway spend ledger): 0700, owned by the uid they run as
    (SGW_RUN_UID: the invoking user on Linux; chowned to 10001 when bootstrap runs as root)."""
    if os.name == "nt":
        return
    path.chmod(0o700)
    if sys.platform.startswith("linux") and os.getuid() == 0:  # type: ignore[attr-defined,unused-ignore]
        for item in (path, *path.rglob("*")):
            os.chown(item, CONTAINER_UID, CONTAINER_GID)  # type: ignore[attr-defined,unused-ignore]


def ensure_audit_key() -> AuditSetup:
    """Keep the active Ed25519 key when there is one, otherwise create it (no chain record: the database may
    be down; `sgw audit keygen` records rotations). Never rotates an existing key."""
    from sgw.approval.signer import AuditPaths, Keyring, generate_key

    keyring_path, key_dir, anchors = audit_dirs()
    paths = AuditPaths(keyring=keyring_path, key_dir=key_dir, anchors=anchors)
    keyring = Keyring.load(keyring_path)
    created = False
    if keyring.active is None:
        active = generate_key(paths, datetime.now(UTC)).key_id
        created = True
    else:
        active = keyring.active
        if not paths.private_key(active).is_file():
            raise CliError(
                f"keyring names active key {active} but {paths.private_key(active)} is missing; restore it, "
                "or rotate on purpose with `uv run sgw audit keygen`"
            )
    anchors.mkdir(parents=True, exist_ok=True)
    secure_audit_paths(paths.private_key(active))
    return AuditSetup(active, created, keyring_path, key_dir, anchors)


def secure_audit_paths(active_pem: Path) -> None:
    if os.name == "nt":
        return
    keyring_path, key_dir, anchors = audit_dirs()
    key_dir.chmod(0o700)
    for pem in key_dir.glob("*.pem"):
        pem.chmod(0o600)
    if sys.platform.startswith("linux") and os.getuid() == 0:  # type: ignore[attr-defined,unused-ignore]
        for path in (keyring_path.parent, anchors, key_dir, *key_dir.glob("*.pem"), *anchors.rglob("*")):
            os.chown(path, CONTAINER_UID, CONTAINER_GID)  # type: ignore[attr-defined,unused-ignore]
        if keyring_path.exists():
            os.chown(keyring_path, CONTAINER_UID, CONTAINER_GID)  # type: ignore[attr-defined,unused-ignore]


def runtime_dsn_for_containers() -> str:
    password = read_env_file(secrets_dir() / "postgres.env")["SGW_RUNTIME_PASSWORD"]
    return f"postgresql://{DB_RUNTIME}:{password}@postgres:5432/{DB_NAME}"
