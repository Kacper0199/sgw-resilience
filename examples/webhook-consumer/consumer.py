# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Example receiver for SGW webhooks: HTTPS, signature check, replay window, de-duplication.

Standard library only, so an integrator can read every line that guards their system. Run:

    SGW_WEBHOOK_SECRETS=whsec_... uv run examples/webhook-consumer/consumer.py \
        --cert server.pem --key server-key.pem --port 8701 --out received.jsonl

`SGW_WEBHOOK_SECRETS` holds one secret, or two separated by a comma while the platform rotates them
(the header then carries one `v1=` per active secret and either match is accepted).

For every POST it checks, in order: body size, `SGW-Signature` format, timestamp within 300 s of this
machine's clock (replay window), HMAC-SHA256 over `<t>.<SGW-Webhook-Id>.<raw body>` against each secret in
constant time, then `SGW-Webhook-Id` against the ids already accepted. A new event is appended to `--out`
(one JSON line) and answered 200; a duplicate is answered 200 without processing (the platform stops
retrying); a bad signature or stale timestamp is answered 401 and logged. Verify before parsing: the body is
only decoded after the signature matched.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import ssl
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIGNATURE_HEADER = "SGW-Signature"
ID_HEADER = "SGW-Webhook-Id"
TOLERANCE_S = 300
MAX_BODY = 1 << 20
SECRETS_ENV = "SGW_WEBHOOK_SECRETS"


class Rejected(Exception):
    pass


def verify(secrets: list[bytes], header: str, delivery_id: str, body: bytes, now: int) -> int:
    """Raises `Rejected` unless the header carries a fresh, matching signature; returns its timestamp."""
    pairs = [item.strip().split("=", 1) for item in header.split(",") if "=" in item]
    stamps = [v for k, v in pairs if k == "t"]
    candidates = [v for k, v in pairs if k == "v1"]
    if len(stamps) != 1 or not stamps[0].isdigit() or not candidates:
        raise Rejected("malformed signature header")
    timestamp = int(stamps[0])
    if abs(now - timestamp) > TOLERANCE_S:
        raise Rejected("timestamp outside the replay window")
    message = f"{timestamp}.{delivery_id}.".encode() + body
    for secret in secrets:
        expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(expected, c) for c in candidates):
            return timestamp
    raise Rejected("signature mismatch")


class Store:
    """Accepted delivery ids (reloaded from the output file, so a restart still de-duplicates)."""

    def __init__(self, out: Path) -> None:
        self.out = out
        self.lock = threading.Lock()
        self.seen: set[str] = set()
        if out.exists():
            for line in out.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.seen.add(json.loads(line)["delivery_id"])

    def accept(self, delivery_id: str, event: dict[str, object]) -> bool:
        with self.lock:
            if delivery_id in self.seen:
                return False
            record = {
                "delivery_id": delivery_id,
                "received_at": datetime.now(UTC).isoformat(),
                "event": event,
            }
            with self.out.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            self.seen.add(delivery_id)
            return True


def make_handler(secrets: list[bytes], store: Store, path: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "sgw-example-consumer/1"

        def _answer(self, status: int, message: str) -> None:
            body = json.dumps({"status": message}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._answer(
                200 if self.path == "/healthz" else 404, "ok" if self.path == "/healthz" else "not found"
            )

        def do_POST(self) -> None:  # noqa: N802
            if self.path != path:
                self._answer(404, "not found")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._answer(413, "body missing or too large")
                return
            body = self.rfile.read(length)
            delivery_id = self.headers.get(ID_HEADER, "")
            try:
                if not delivery_id:
                    raise Rejected("missing delivery id")
                verify(secrets, self.headers.get(SIGNATURE_HEADER, ""), delivery_id, body, int(time.time()))
            except Rejected as exc:
                self.log_message("rejected %s: %s", delivery_id or "-", exc)
                self._answer(401, "rejected")
                return
            event = json.loads(body)
            if store.accept(delivery_id, event):
                self.log_message(
                    "accepted %s %s seq=%s", delivery_id, event.get("type"), event.get("ledger_seq")
                )
                self._answer(200, "accepted")
            else:
                self._answer(200, "duplicate")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8701)
    parser.add_argument("--path", default="/hooks/sgw")
    parser.add_argument("--cert", required=True, help="PEM server certificate (chain)")
    parser.add_argument("--key", required=True, help="PEM private key")
    parser.add_argument("--out", default="received.jsonl", help="accepted events, one JSON line each")
    args = parser.parse_args(argv)
    raw = os.environ.get(SECRETS_ENV, "")
    secrets = [s.strip().encode() for s in raw.split(",") if s.strip()]
    if not secrets:
        print(
            f"set {SECRETS_ENV} to the subscription secret (two, comma-separated, during rotation)",
            file=sys.stderr,
        )
        return 2
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.cert, args.key)
    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(secrets, Store(Path(args.out)), args.path)
    )
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"listening on https://{args.host}:{args.port}{args.path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
