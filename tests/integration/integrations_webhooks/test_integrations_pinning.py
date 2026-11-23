"""SSRF guard against DNS rebinding (security finding M3): a delivery connects to exactly the address it
checked, while Host, TLS SNI and certificate verification keep using the hostname."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from sgw.integrations.delivery import Claim, send
from sgw.integrations.urls import UrlPolicy
from sgw.integrations.worker import tls_context, webhook_client

from .tls_testkit import Pems, launch_consumer, make_pems

PUBLIC = "93.184.216.34"
REBIND_HOST = "hooks.rebind-ridge.test"
REBIND_PORT = 8704
TLS_HOST = "hooks.lakemont-water.test"
TLS_PORT = 8703
MISMATCH_PORT = 8705
SECRET = "whsec_pinning-test-secret-not-real-000000000000"  # noqa: S105


def claim(url: str) -> Claim:
    return Claim(
        delivery_id="whd_pinning0000000000000000000000",
        subscription_id="whs_pinning",
        url=url,
        attempts=0,
        event_id="6a3f1c0e-2b4d-5e6f-8a9b-0c1d2e3f4a5b",
        event_type="DecisionApproved",
        ledger_seq=7,
        event_time=datetime(2024, 9, 26, 18, 0, tzinfo=UTC),
        payload={"proposal_id": "PRP-CREW-AIK-0926A"},
    )


@pytest.fixture
async def loopback_listener() -> AsyncIterator[list[int]]:
    """A plain TCP listener on the loopback port a rebinding attacker would aim at; counts connections."""
    accepted: list[int] = []

    async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.append(1)
        writer.close()

    server = await asyncio.start_server(on_connect, "127.0.0.1", REBIND_PORT)
    try:
        yield accepted
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
def system_dns_points_inward(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The system resolver answers 127.0.0.1 for the rebinding host (what httpx would get if it resolved)."""
    asked: list[str] = []
    real = socket.getaddrinfo

    def fake(host: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(host, str) and host.endswith(".test"):
            asked.append(host)
            return real("127.0.0.1", *args, **kwargs)
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    yield asked


async def test_rebinding_between_subscribe_and_send_is_refused(
    loopback_listener: list[int], system_dns_points_inward: list[str]
) -> None:
    answers = iter([[PUBLIC], ["127.0.0.1"]])
    policy = UrlPolicy(resolver=lambda host, port: next(answers))
    url = f"https://{REBIND_HOST}:{REBIND_PORT}/hooks"
    policy.check(url)
    result = await send(
        lambda: httpx.AsyncClient(),
        claim(url),
        [SECRET.encode()],
        unix_now=0,
        url_policy=policy,
    )
    assert result.status is None and result.error is not None and result.error.startswith("url refused")
    assert loopback_listener == [] and system_dns_points_inward == []


async def test_send_connects_to_the_checked_address_not_a_fresh_lookup(
    loopback_listener: list[int], system_dns_points_inward: list[str]
) -> None:
    seen: list[httpx.Request] = []

    def network(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    policy = UrlPolicy(resolver=lambda host, port: [PUBLIC])
    url = f"https://{REBIND_HOST}:{REBIND_PORT}/hooks"
    result = await send(
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(network)),
        claim(url),
        [SECRET.encode()],
        unix_now=0,
        url_policy=policy,
    )
    assert result.status == 204
    (request,) = seen
    assert request.url.host == PUBLIC and request.url.port == REBIND_PORT and request.url.path == "/hooks"
    assert request.headers["host"] == f"{REBIND_HOST}:{REBIND_PORT}"
    assert request.extensions["sni_hostname"] == REBIND_HOST
    assert loopback_listener == [] and system_dns_points_inward == []


async def test_any_private_answer_refuses_even_with_a_public_one() -> None:
    policy = UrlPolicy(resolver=lambda host, port: [PUBLIC, "169.254.169.254"])
    result = await send(
        lambda: httpx.AsyncClient(), claim(f"https://{REBIND_HOST}/x"), [b"k"], unix_now=0, url_policy=policy
    )
    assert result.error is not None and "non-public" in result.error


@pytest.fixture(scope="module")
def tls_pems(tmp_path_factory: pytest.TempPathFactory) -> Pems:
    return make_pems(tmp_path_factory.mktemp("tls-name"), dns_name=TLS_HOST)


@pytest.fixture(scope="module")
def other_pems(tmp_path_factory: pytest.TempPathFactory) -> Pems:
    return make_pems(tmp_path_factory.mktemp("tls-other"), dns_name="other.lakemont-water.test")


def runner_client(pems: Pems) -> httpx.AsyncClient:
    return webhook_client(tls_context(str(pems.ca)))


async def test_tls_verifies_the_hostname_over_the_pinned_address(
    tls_pems: Pems, other_pems: Pems, tmp_path: Path, system_dns_points_inward: list[str]
) -> None:
    out = tmp_path / "received.jsonl"
    good = launch_consumer(tls_pems, [SECRET], out, TLS_PORT)
    bad = launch_consumer(other_pems, [SECRET], tmp_path / "other.jsonl", MISMATCH_PORT)
    try:
        allow = frozenset({f"{TLS_HOST}:{TLS_PORT}", f"{TLS_HOST}:{MISMATCH_PORT}"})
        policy = UrlPolicy(allow_hosts=allow, resolver=lambda host, port: ["127.0.0.1"])
        now = int(datetime.now(UTC).timestamp())
        ok = await send(
            lambda: runner_client(tls_pems),
            claim(f"https://{TLS_HOST}:{TLS_PORT}/hooks/sgw"),
            [SECRET.encode()],
            unix_now=now,
            url_policy=policy,
        )
        assert ok.status == 200, ok.error
        record = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
        assert record["event"]["data"] == {"proposal_id": "PRP-CREW-AIK-0926A"}
        refused = await send(
            lambda: runner_client(tls_pems),
            claim(f"https://{TLS_HOST}:{MISMATCH_PORT}/hooks/sgw"),
            [SECRET.encode()],
            unix_now=now,
            url_policy=policy,
        )
        assert refused.status is None and refused.error is not None
        assert "CERTIFICATE_VERIFY_FAILED" in refused.error or "certificate" in refused.error.lower()
        assert not (tmp_path / "other.jsonl").exists()
        assert system_dns_points_inward == []
    finally:
        for proc in (good, bad):
            proc.terminate()
            proc.wait(10)
