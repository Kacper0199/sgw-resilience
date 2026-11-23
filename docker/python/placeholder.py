"""Stand-in process for api, worker and llm-gateway until their packages land (W1).

Serves /healthz (process alive) and /readyz (dependencies reachable: Postgres when
SGW_DATABASE_URL is set). Replaced by setting `command:` in compose.yaml.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICE = os.environ.get("SGW_SERVICE", "unknown")
PORT = int(os.environ.get("SGW_HEALTH_PORT", "8000"))


def database_ready() -> tuple[bool, str]:
    url = os.environ.get("SGW_DATABASE_URL")
    if not url:
        return True, "no database configured"
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as error:
        return False, type(error).__name__
    return True, "database ok"


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        base = {"service": SERVICE, "placeholder": True}
        if self.path == "/healthz":
            self._reply(200, {**base, "status": "alive"})
        elif self.path == "/readyz":
            ok, detail = database_ready()
            self._reply(
                200 if ok else 503, {**base, "status": "ready" if ok else "not ready", "detail": detail}
            )
        else:
            self._reply(404, base)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()  # noqa: S104
