"""The integration master key and the keys derived from it.

One 32-byte master key (`SGW_INTEGRATION_KEY`, hex or url-safe base64; else `var/secrets/integration.key`,
created 0600 on first use) feeds HKDF-SHA256 with separate labels:
- the token pepper: API tokens are stored as HMAC-SHA256(pepper, token), so a database dump alone
  cannot be brute-forced or replayed;
- the AES-256-GCM key that seals webhook signing secrets at rest (the delivery worker must recover
  them to sign).
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

KEY_ENV = "SGW_INTEGRATION_KEY"
KEY_FILE = "integration.key"
KEY_BYTES = 32
_PEPPER_INFO = b"sgw integration token pepper v1"
_SEAL_INFO = b"sgw webhook secret seal v1"


class IntegrationKeyError(RuntimeError):
    pass


def _derive(master: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(master)


def decode_key(raw: str) -> bytes:
    text = raw.strip()
    try:
        value = bytes.fromhex(text)
    except ValueError:
        try:
            value = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        except (binascii.Error, ValueError) as exc:
            raise IntegrationKeyError(f"{KEY_ENV} must be hex or url-safe base64") from exc
    if len(value) < KEY_BYTES:
        raise IntegrationKeyError(f"{KEY_ENV} must hold at least {KEY_BYTES} bytes")
    return value


@dataclass(frozen=True)
class IntegrationKeys:
    pepper: bytes
    seal_key: bytes

    @classmethod
    def from_master(cls, master: bytes) -> IntegrationKeys:
        if len(master) < KEY_BYTES:
            raise IntegrationKeyError(f"master key must hold at least {KEY_BYTES} bytes")
        return cls(pepper=_derive(master, _PEPPER_INFO), seal_key=_derive(master, _SEAL_INFO))

    def seal(self, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return nonce, AESGCM(self.seal_key).encrypt(nonce, plaintext, aad)

    def open(self, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
        return AESGCM(self.seal_key).decrypt(nonce, ciphertext, aad)


def _key_file() -> Path:
    from sgw.cli.support import secrets_dir

    return secrets_dir() / KEY_FILE


def load_keys(env: dict[str, str] | None = None, key_file: Path | None = None) -> IntegrationKeys:
    """The env var when present, else the key file. Present but blank is a misconfiguration (a container
    whose `${SGW_INTEGRATION_KEY:-}` expanded to nothing) and fails: a silent file fallback would give each
    container its own pepper and seal key, so tokens and webhook secrets would not verify across services."""
    source = os.environ if env is None else env
    if KEY_ENV in source:
        raw = source[KEY_ENV]
        if not raw.strip():
            raise IntegrationKeyError(f"{KEY_ENV} is set but empty; set the shared key or unset the variable")
        return IntegrationKeys.from_master(decode_key(raw))
    return IntegrationKeys.from_master(decode_key(ensure_key_file(key_file or _key_file())))


def ensure_key_file(path: Path) -> str:
    """The master key held in `path`, created 0600 with `secrets.token_hex(32)` when absent."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(secrets.token_hex(KEY_BYTES) + "\n")
    text = path.read_text(encoding="utf-8").strip()
    decode_key(text)
    return text
