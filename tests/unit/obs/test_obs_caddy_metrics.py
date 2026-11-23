from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = ROOT / "infra" / "caddy" / "Caddyfile"
DOCKER = shutil.which("docker")


def _caddy_image() -> str:
    """The pinned upstream Caddy that docker/caddy/Dockerfile builds the edge image on."""
    dockerfile = (ROOT / "docker" / "caddy" / "Dockerfile").read_text()
    return next(
        line.split("=", 1)[1] for line in dockerfile.splitlines() if line.startswith("ARG CADDY_IMAGE=")
    )


def test_compose_builds_the_edge_image_on_the_pinned_caddy() -> None:
    caddy = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]["caddy"]
    assert caddy["build"]["dockerfile"] == "docker/caddy/Dockerfile"
    assert caddy["image"].startswith("sgw/caddy:")
    assert "@sha256:" in _caddy_image()


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as error:
        return int(error.code)


def _port(name: str, inner: int) -> int:
    assert DOCKER
    out = subprocess.run(  # noqa: S603
        [DOCKER, "port", name, f"{inner}/tcp"], capture_output=True, text=True, check=True
    ).stdout
    return int(out.splitlines()[0].rsplit(":", 1)[1])


@pytest.fixture(scope="module")
def caddy() -> Iterator[tuple[int, int]]:
    assert DOCKER
    name = f"wp39-caddy-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(  # noqa: S603
        [
            DOCKER,
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-v",
            f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
            "-v",
            f"{ROOT / 'infra' / 'caddy' / 'site'}:/srv:ro",
            "-p",
            "127.0.0.1::8080",
            "-p",
            "127.0.0.1::8000",
            _caddy_image(),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    try:
        ui, relay = _port(name, 8080), _port(name, 8000)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if _status(f"http://127.0.0.1:{ui}/healthz") == 200:
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.5)
        yield ui, relay
    finally:
        subprocess.run([DOCKER, "rm", "-f", name], capture_output=True, check=False)  # noqa: S603


def test_caddyfile_names_the_block_in_both_public_sites() -> None:
    text = CADDYFILE.read_text()
    assert "handle /metrics {\n\t\trespond 404" in text
    assert ":8000 {\n\timport relay_headers\n\trespond /metrics 404" in text


@pytest.mark.slow
@pytest.mark.skipif(DOCKER is None, reason="no docker CLI")  # sgw-allow-skip: Windows unit runner
def test_pinned_caddy_refuses_metrics_on_ui_and_api_relay(caddy: tuple[int, int]) -> None:
    ui, relay = caddy
    assert _status(f"http://127.0.0.1:{ui}/healthz") == 200
    for port in (ui, relay):
        for path in ("/metrics", "/METRICS", "/./metrics"):
            assert _status(f"http://127.0.0.1:{port}{path}") == 404, (port, path)
    assert _status(f"http://127.0.0.1:{relay}/api/me") == 502
