"""A missing or unreachable policy engine reaches the user in plain words; the technical cause stays in the
exception and the log (R27 DR Blocker 1: the toast showed the raw OPA message)."""

from __future__ import annotations

import httpx
import pytest

from sgw.approval.errors import PolicyUnavailableError
from sgw.approval.policy import PolicyNotLoadedError
from sgw.dispatch.policy import OpaDispatch

TECHNICAL = ("OPA", "opa", "policy not loaded", "dispatch/", "rego", "http")


def _undefined(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


@pytest.mark.parametrize(
    "error",
    [
        PolicyNotLoadedError("OPA returned no decision for dispatch/propose (policy not loaded?)"),
        PolicyUnavailableError("OPA query dispatch/propose failed: ConnectError"),
    ],
)
def test_body_is_plain_words(error: PolicyUnavailableError) -> None:
    body = error.body()["error"]
    assert body["code"] == error.code
    assert not any(word in body["message"] for word in TECHNICAL), body["message"]
    assert "nothing was changed" in body["message"]
    assert body["details"] == {}
    assert "OPA" in str(error)


def test_undefined_dispatch_decision_keeps_the_cause_for_the_log() -> None:
    client = httpx.Client(base_url="http://opa.test", transport=httpx.MockTransport(_undefined))
    with pytest.raises(PolicyNotLoadedError) as raised:
        OpaDispatch("http://opa.test", client=client).propose({"subject": {"roles": ["logistics_chief"]}})
    assert "dispatch/propose" in str(raised.value)
    assert "OPA" not in raised.value.body()["error"]["message"]
