"""In-process Ed25519 signer for audit checkpoints, with a keyring that records key ids and rotation.

Private keys live outside the repository (default `var/secrets/audit/`, file mode 0600); the keyring
(`var/audit/keyring.json`) holds only public keys, the active key id and each key's validity window, and is
the verifier's trust root. A key id is `ed25519:` plus the first 16 hex digits of sha256(raw public key).
Rotation adds a key, makes it active and closes the previous key's window; old public keys stay trusted for
checkpoints anchored inside their window. Tests use `Ed25519Signer.generate()` (ephemeral, never written).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sgw.contracts.base import utc_iso

ALGORITHM = "ed25519"
KEYRING_ENV = "SGW_AUDIT_KEYRING"
KEY_DIR_ENV = "SGW_AUDIT_KEY_DIR"
ANCHORS_ENV = "SGW_AUDIT_ANCHORS_DIR"
ACTIVE_KEY_ENV = "SGW_AUDIT_ACTIVE_KEY"
SIGNING_ENV = "SGW_AUDIT_SIGNING"


class SignerError(RuntimeError):
    pass


def key_id_for(public_raw: bytes) -> str:
    return f"{ALGORITHM}:{hashlib.sha256(public_raw).hexdigest()[:16]}"


def _public_raw(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)


class Ed25519Signer:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key
        self.public_raw = _public_raw(private_key.public_key())
        self.key_id = key_id_for(self.public_raw)

    @classmethod
    def generate(cls) -> Ed25519Signer:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_pem(cls, path: Path) -> Ed25519Signer:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise SignerError(f"{path} does not hold an Ed25519 private key")
        return cls(key)

    @property
    def public_key_hex(self) -> str:
        return self.public_raw.hex()

    def sign(self, message: bytes) -> str:
        return self._key.sign(message).hex()

    def write_pem(self, path: Path) -> None:
        """Write the private key once, 0600, refusing to overwrite."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            path.parent.chmod(0o700)
        pem = self._key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(pem)


def verify_signature(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        key.verify(bytes.fromhex(signature_hex), message)
    except (InvalidSignature, ValueError):
        return False
    return True


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key: str
    created_at: str
    retired_at: str | None = None

    def valid_at(self, at: datetime) -> bool:
        if at < datetime.fromisoformat(self.created_at):
            return False
        return self.retired_at is None or at <= datetime.fromisoformat(self.retired_at)


@dataclass(frozen=True)
class Keyring:
    """Trusted public keys (the verifier's trust root) and the active signing key id."""

    active: str | None = None
    keys: tuple[TrustedKey, ...] = field(default_factory=tuple)

    def get(self, key_id: str) -> TrustedKey | None:
        return next((k for k in self.keys if k.key_id == key_id), None)

    def rotate(self, signer: Ed25519Signer, at: datetime) -> Keyring:
        if self.get(signer.key_id) is not None:
            raise SignerError(f"key {signer.key_id} is already in the keyring")
        stamp = utc_iso(at)
        keys = tuple(replace(k, retired_at=stamp) if k.key_id == self.active else k for k in self.keys)
        added = TrustedKey(key_id=signer.key_id, public_key=signer.public_key_hex, created_at=stamp)
        return Keyring(active=signer.key_id, keys=(*keys, added))

    def to_json(self) -> dict[str, Any]:
        return {
            "algorithm": ALGORITHM,
            "active": self.active,
            "keys": [
                {
                    "key_id": k.key_id,
                    "public_key": k.public_key,
                    "created_at": k.created_at,
                    "retired_at": k.retired_at,
                }
                for k in self.keys
            ],
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> Keyring:
        keys = tuple(
            TrustedKey(
                key_id=str(k["key_id"]),
                public_key=str(k["public_key"]),
                created_at=str(k["created_at"]),
                retired_at=k.get("retired_at"),
            )
            for k in raw.get("keys", [])
        )
        for k in keys:
            if key_id_for(bytes.fromhex(k.public_key)) != k.key_id:
                raise SignerError(f"keyring entry {k.key_id} does not match its public key")
        return cls(active=raw.get("active"), keys=keys)

    @classmethod
    def load(cls, path: Path) -> Keyring:
        if not path.is_file():
            return cls()
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=2) + "\n", encoding="utf-8", newline="\n")
        tmp.replace(path)


@dataclass(frozen=True)
class AuditPaths:
    keyring: Path
    key_dir: Path
    anchors: Path

    def private_key(self, key_id: str) -> Path:
        return self.key_dir / f"{key_id.replace(':', '-')}.pem"


def default_paths() -> AuditPaths:
    """Env overrides first; otherwise `var/` of the shared state root (works from a git worktree)."""
    from sgw.cli.support import secrets_dir, var_dir

    keyring = os.environ.get(KEYRING_ENV)
    key_dir = os.environ.get(KEY_DIR_ENV)
    anchors = os.environ.get(ANCHORS_ENV)
    return AuditPaths(
        keyring=Path(keyring) if keyring else var_dir() / "audit" / "keyring.json",
        key_dir=Path(key_dir) if key_dir else secrets_dir() / "audit",
        anchors=Path(anchors) if anchors else var_dir() / "audit" / "anchors",
    )


def generate_key(paths: AuditPaths, at: datetime) -> Ed25519Signer:
    """Create a key, write it 0600, and make it the active key (rotating out the previous one)."""
    signer = Ed25519Signer.generate()
    keyring = Keyring.load(paths.keyring).rotate(signer, at)
    signer.write_pem(paths.private_key(signer.key_id))
    keyring.save(paths.keyring)
    return signer


def active_signer(paths: AuditPaths) -> Ed25519Signer | None:
    """The keyring's active key. With SGW_AUDIT_ACTIVE_KEY set (the deployment pin) the keyring must name
    that key as active, so an edited keyring cannot switch the signer to a key the operator did not choose."""
    keyring = Keyring.load(paths.keyring)
    pinned = os.environ.get(ACTIVE_KEY_ENV)
    if pinned and keyring.active != pinned:
        raise SignerError(f"{ACTIVE_KEY_ENV}={pinned} but the keyring's active key is {keyring.active}")
    if keyring.active is None:
        return None
    path = paths.private_key(keyring.active)
    if not path.is_file():
        raise SignerError(f"active key {keyring.active} has no private key file in {paths.key_dir}")
    signer = Ed25519Signer.from_pem(path)
    if signer.key_id != keyring.active:
        raise SignerError(f"private key file for {keyring.active} holds key {signer.key_id}")
    return signer
