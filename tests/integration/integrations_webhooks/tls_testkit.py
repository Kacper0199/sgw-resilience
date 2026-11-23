"""A throwaway CA and a server certificate for 127.0.0.1, written as PEM files."""

from __future__ import annotations

import ipaddress
import os
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class Pems:
    ca: Path
    cert: Path
    key: Path


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_pems(folder: Path, dns_name: str | None = None) -> Pems:
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("WP-37 test CA"))
        .issuer_name(_name("WP-37 test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(dns_name or "127.0.0.1"))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(dns_name)] if dns_name else [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    pems = Pems(folder / "ca.pem", folder / "server.pem", folder / "server-key.pem")
    pems.ca.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    pems.cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    pems.key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return pems


CONSUMER = Path(__file__).resolve().parents[3] / "examples" / "webhook-consumer" / "consumer.py"


def launch_consumer(pems: Pems, secrets: list[str], out: Path, port: int) -> subprocess.Popen[str]:
    """The example consumer as its own process on 127.0.0.1:<port>; waits until it answers over TLS."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SGW_")}
    env["SGW_WEBHOOK_SECRETS"] = ",".join(secrets)
    args = [sys.executable, str(CONSUMER), "--cert", str(pems.cert), "--key", str(pems.key)]
    args += ["--port", str(port), "--out", str(out)]
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # noqa: S603
    probe = ssl.create_default_context(cafile=str(pems.ca))
    probe.check_hostname = False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"https://127.0.0.1:{port}/healthz", verify=probe, timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("consumer did not start")
