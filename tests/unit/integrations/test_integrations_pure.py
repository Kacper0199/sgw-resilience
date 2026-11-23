from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from sgw.contracts import webhooks
from sgw.contracts.vocab import ApiScope
from sgw.integrations import backoff, signing, tokens
from sgw.integrations.keys import IntegrationKeyError, IntegrationKeys, decode_key, load_keys
from sgw.integrations.payload import body_bytes, delivery_id, event_v1
from sgw.integrations.urls import UrlPolicy, UrlRefused

NOW = datetime(2024, 9, 26, 18, 0, tzinfo=UTC)
KEYS = IntegrationKeys.from_master(bytes(range(32)))


def principal(*scopes: ApiScope) -> tokens.TokenPrincipal:
    return tokens.TokenPrincipal("itk000000000001", "t", frozenset(scopes), "admin_01", NOW)


def test_token_format_is_prefixed_parseable_and_hashed_with_the_pepper() -> None:
    issued = tokens.new_token()
    assert issued.token.startswith("sgwi_itk") and tokens.parse_token(issued.token) == issued.token_id
    digest = tokens.hash_token(KEYS.pepper, issued.token)
    assert len(digest) == 64 and issued.token not in digest
    other = IntegrationKeys.from_master(bytes(range(1, 33)))
    assert tokens.hash_token(other.pepper, issued.token) != digest
    assert tokens.new_token().token != issued.token


@pytest.mark.parametrize(
    "raw",
    ["", "sgwi_", "Bearer sgwi_x", "sgwi_itk0000_" + "a" * 64, "sgwi_itk000000000001_" + "g" * 64, "x" * 500],
)
def test_malformed_tokens_parse_to_none(raw: str) -> None:
    assert tokens.parse_token(raw) is None


def test_event_scopes_follow_least_privilege() -> None:
    reader = principal(ApiScope.DECISIONS_READ)
    assert reader.readable_events() == {"DecisionApproved"}
    assert reader.missing_for_events(["DecisionApproved"]) == []
    assert reader.missing_for_events(["DecisionApproved", "ClockBreached", "CommitmentDrifted"]) == [
        "clocks:read",
        "commitments:read",
    ]
    assert set(tokens.EVENT_SCOPE) == set(webhooks.WebhookType.__args__)  # type: ignore[attr-defined]
    assert all(not s.value.endswith(":write") and "approve" not in s.value for s in ApiScope)


def test_backoff_doubles_with_jitter_caps_and_dead_letters() -> None:
    low = backoff.RetryPolicy(base_s=10, cap_s=300, max_attempts=5, jitter=lambda: 0.0)
    high = backoff.RetryPolicy(base_s=10, cap_s=300, max_attempts=5, jitter=lambda: 1.0)
    assert [low.delay_s(n) for n in range(1, 7)] == [5, 10, 20, 40, 80, 150]
    assert [high.delay_s(n) for n in range(1, 7)] == [10, 20, 40, 80, 160, 300]
    assert low.delay_s(1, retry_after_s=120) == 120 and low.delay_s(1, retry_after_s=9999) == 300
    assert not low.exhausted(4) and low.exhausted(5)
    assert backoff.RetryPolicy().worst_case_total_s() < 3 * 3600
    with pytest.raises(ValueError):
        low.delay_s(0)


def test_outcomes_and_retry_after() -> None:
    assert [backoff.outcome(s) for s in (200, 204, 299, 300, 404, 410, 500, None)] == [
        "delivered",
        "delivered",
        "delivered",
        "retry",
        "retry",
        "gone",
        "retry",
        "retry",
    ]
    assert backoff.parse_retry_after("30") == 30 and backoff.parse_retry_after("soon") is None
    assert backoff.parse_retry_after("-1") is None and backoff.parse_retry_after(None) is None


def _resolver(mapping: dict[str, list[str]]):  # type: ignore[no-untyped-def]
    def resolve(host: str, port: int) -> list[str]:
        if host not in mapping:
            raise OSError("nxdomain")
        return mapping[host]

    return resolve


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://hooks.lakemont-water.example/x", "https"),
        ("https://user:pw@hooks.lakemont-water.example/x", "credentials"),
        ("https://127.0.0.1/x", "non-public"),
        ("https://10.4.2.9/x", "non-public"),
        ("https://169.254.169.254/latest/meta-data", "non-public"),
        ("https://[::1]/x", "non-public"),
        ("https://[::ffff:10.0.0.1]/x", "non-public"),
        ("https://intranet.lakemont-water.example/x", "non-public"),
        ("https://nowhere.invalid/x", "resolve"),
        ("https://hooks.lakemont-water.example/x#frag", "fragment"),
    ],
)
def test_url_policy_refuses_ssrf_targets(url: str, reason: str) -> None:
    policy = UrlPolicy(
        resolver=_resolver(
            {
                "hooks.lakemont-water.example": ["93.184.216.34"],
                "intranet.lakemont-water.example": ["192.168.7.3"],
            }
        )
    )
    with pytest.raises(UrlRefused, match=reason):
        policy.check(url)


def test_url_policy_allows_public_and_allowlisted_hosts() -> None:
    policy = UrlPolicy(
        allow_hosts=frozenset({"127.0.0.1:8701"}),
        resolver=_resolver({"hooks.lakemont-water.example": ["93.184.216.34"]}),
    )
    policy.check("https://hooks.lakemont-water.example/sgw")
    policy.check("https://127.0.0.1:8701/hooks")
    with pytest.raises(UrlRefused):
        policy.check("https://127.0.0.1:8702/hooks")
    env = {"SGW_WEBHOOK_ALLOW_HOSTS": " 127.0.0.1:8701, LOCALHOST:8702 "}
    assert UrlPolicy.from_env(env).allow_hosts == {"127.0.0.1:8701", "localhost:8702"}


def test_sealed_secret_is_bound_to_its_subscription_and_slot() -> None:
    secret = signing.new_secret()
    assert secret.startswith("whsec_") and len(secret) > 40
    sealed = signing.seal(KEYS, "whs_a", 1, secret, NOW)
    assert secret.encode() not in sealed.ciphertext and sealed.secret_hint == secret[-4:]
    assert signing.unseal(KEYS, "whs_a", sealed) == secret.encode()
    with pytest.raises(Exception):  # noqa: B017, PT011
        signing.unseal(KEYS, "whs_b", sealed)
    moved = signing.SealedSecret(2, sealed.nonce, sealed.ciphertext, sealed.secret_hint, NOW, None)
    with pytest.raises(Exception):  # noqa: B017, PT011
        signing.unseal(KEYS, "whs_a", moved)


def test_rotation_signs_with_both_secrets_until_the_old_one_retires() -> None:
    old, new = signing.new_secret(), signing.new_secret()
    s1 = signing.seal(KEYS, "whs_a", 1, old, NOW)
    s1 = signing.SealedSecret(1, s1.nonce, s1.ciphertext, s1.secret_hint, NOW, NOW + timedelta(hours=24))
    s2 = signing.seal(KEYS, "whs_a", 2, new, NOW)
    during = signing.signing_keys(KEYS, "whs_a", [s1, s2], NOW + timedelta(hours=1))
    assert during == [new.encode(), old.encode()]
    after = signing.signing_keys(KEYS, "whs_a", [s1, s2], NOW + timedelta(hours=25))
    assert after == [new.encode()]
    body, ts = b'{"a":1}', int(NOW.timestamp())
    header = webhooks.sign_rotating(during, timestamp=ts, delivery_id="whd_1", body=body)
    for secret in (old, new):
        webhooks.verify(secret.encode(), header=header, delivery_id="whd_1", body=body, now=ts)
    with pytest.raises(webhooks.SignatureError, match="mismatch"):
        webhooks.verify(b"whsec_other", header=header, delivery_id="whd_1", body=body, now=ts)


def test_replay_window_rejects_old_and_future_timestamps() -> None:
    body, ts, key = b"{}", 1_727_373_600, b"whsec_k"
    header = webhooks.sign(key, timestamp=ts, delivery_id="whd_1", body=body)
    webhooks.verify(key, header=header, delivery_id="whd_1", body=body, now=ts + 300)
    for now in (ts + 301, ts - 301):
        with pytest.raises(webhooks.SignatureError, match="tolerance"):
            webhooks.verify(key, header=header, delivery_id="whd_1", body=body, now=now)


def test_body_is_canonical_and_delivery_id_stable() -> None:
    event = event_v1(
        event_id="7d3e1c3a-6c1f-5b0e-9f55-0a5e17c09a0a",
        event_type="DecisionApproved",
        ledger_seq=42,
        event_time=NOW,
        payload={"z": 1, "a": [2, 1]},
    )
    raw = body_bytes(event)
    assert raw == body_bytes(event) and b" " not in raw
    assert list(json.loads(raw)) == sorted(json.loads(raw))
    assert json.loads(raw)["created_at"] == "2024-09-26T18:00:00Z"
    assert delivery_id("whs_a", event.id) == delivery_id("whs_a", event.id) != delivery_id("whs_b", event.id)


def test_master_key_from_env_or_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IntegrationKeyError):
        decode_key("abcd")
    from_env = load_keys({"SGW_INTEGRATION_KEY": "11" * 32})
    assert from_env.pepper != from_env.seal_key
    path = tmp_path / "secrets" / "integration.key"
    first = load_keys({}, key_file=path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_keys({}, key_file=path) == first


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_key_in_the_environment_fails_instead_of_falling_back(tmp_path, blank: str) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "integration.key"
    with pytest.raises(IntegrationKeyError, match="set but empty"):
        load_keys({"SGW_INTEGRATION_KEY": blank}, key_file=path)
    assert not path.exists()


def test_api_and_worker_refuse_to_start_with_a_blank_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from sgw.api.routers import v1_integrations
    from sgw.integrations.worker import WebhookRunner

    monkeypatch.setenv("SGW_INTEGRATION_KEY", "")
    with pytest.raises(IntegrationKeyError):
        WebhookRunner("postgresql://unused/unused")
    app = FastAPI()
    app.include_router(v1_integrations.router)
    with pytest.raises(IntegrationKeyError), TestClient(app):
        pass
    monkeypatch.setenv("SGW_INTEGRATION_KEY", "22" * 32)
    with TestClient(app):
        assert app.state.integration_keys == load_keys({"SGW_INTEGRATION_KEY": "22" * 32})
