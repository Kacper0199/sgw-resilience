"""`/v1` and token admin against a real database: scopes, least privilege, audit of every change."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
from fastapi.testclient import TestClient

from sgw.contracts import golden
from sgw.contracts.webhooks import WebhookType
from sgw.integrations.testkit import ALLOWED_HOST, Db, audit_kinds, bearer, login, new_token

HOOK = f"https://{ALLOWED_HOST}/hooks/sgw"


def admin(client: TestClient, db: Db) -> dict[str, str]:
    return login(client, "admin_01", db.password)


def test_token_is_shown_once_stored_peppered_and_audited(client: TestClient, db: Db) -> None:
    created = new_token(client, admin(client, db), ["decisions:read"])
    token = created["token"]
    assert token.startswith(f"sgwi_{created['token_id']}_") and created["scopes"] == ["decisions:read"]
    with psycopg.connect(db.admin_url) as conn:
        row = conn.execute(
            "SELECT token_hash, created_by FROM api_token WHERE token_id = %s", (created["token_id"],)
        ).fetchone()
    assert row is not None and row[1] == "admin_01" and token not in row[0]
    import hashlib

    assert row[0] != hashlib.sha256(token.encode()).hexdigest()
    kinds = audit_kinds(db.admin_url, f"api_token:{created['token_id']}")
    assert [k for k, _ in kinds] == ["api_token.created"]
    assert token not in str(kinds) and row[0] not in str(kinds)


def test_only_a_stepped_up_platform_admin_creates_tokens(client: TestClient, db: Db) -> None:
    csrf = login(client, "ops_dm_01", db.password)
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    body = {"name": "not mine", "scopes": ["decisions:read"], "expires_at": expires}
    response = client.post("/api/admin/tokens", json=body, headers=csrf)
    assert response.status_code == 403 and response.json()["error"]["code"] == "PLATFORM_ONLY"
    csrf = admin(client, db)
    assert client.post("/api/admin/tokens", json=body).status_code == 403
    past = {**body, "expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
    assert client.post("/api/admin/tokens", json=past, headers=csrf).status_code == 422


def test_bearer_is_required_and_bad_tokens_get_one_answer(client: TestClient, db: Db) -> None:
    good = new_token(client, admin(client, db), ["decisions:read"])["token"]
    client.cookies.clear()
    missing = client.get("/v1/decisions")
    assert missing.status_code == 401 and missing.headers["www-authenticate"].startswith("Bearer")
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    for raw in ("sgwi_nonsense", tampered, "sgwi_itk000000000000_" + "0" * 64):
        response = client.get("/v1/decisions", headers=bearer(raw))
        assert response.status_code == 401 and response.json()["error"]["code"] == "TOKEN_INVALID"
    ok = client.get("/v1/decisions", headers=bearer(good))
    assert ok.status_code == 200
    ids = [d["decision_case_id"] for d in ok.json()]
    assert golden.CASE_CREWS in ids
    one = client.get(f"/v1/decisions/{golden.CASE_CREWS}", headers=bearer(good))
    assert one.status_code == 200 and one.json()["state"] == "proposed"
    assert client.get("/v1/decisions/DC-NOT-THERE", headers=bearer(good)).status_code == 404


def test_session_cookie_does_not_open_v1(client: TestClient, db: Db) -> None:
    admin(client, db)
    assert client.get("/v1/decisions").status_code == 401


def test_read_token_cannot_approve_subscribe_or_read_other_domains(client: TestClient, db: Db) -> None:
    reader = new_token(client, admin(client, db), ["decisions:read"])["token"]
    client.cookies.clear()
    with psycopg.connect(db.admin_url) as conn:
        before = conn.execute(
            "SELECT state, proposal_version FROM proposal WHERE proposal_id = %s", (golden.PROPOSAL_CREWS,)
        ).fetchone()
        approvals = conn.execute("SELECT count(*) FROM approval").fetchone()
    approve = client.post(
        f"/api/proposals/{golden.PROPOSAL_CREWS}/approvals",
        json={"decision": "approve", "proposal_version": 1, "action_hash": "0" * 64},
        headers=bearer(reader),
    )
    assert approve.status_code == 401
    with psycopg.connect(db.admin_url) as conn:
        after = conn.execute(
            "SELECT state, proposal_version FROM proposal WHERE proposal_id = %s", (golden.PROPOSAL_CREWS,)
        ).fetchone()
        assert conn.execute("SELECT count(*) FROM approval").fetchone() == approvals
    assert after == before
    sub = client.post(
        "/v1/webhooks", json={"url": HOOK, "event_types": ["DecisionApproved"]}, headers=bearer(reader)
    )
    assert sub.status_code == 403 and sub.json()["error"]["code"] == "SCOPE_REQUIRED"
    assert client.get("/v1/commitments", headers=bearer(reader)).status_code == 403
    events = client.get("/v1/events?types=ClockBreached", headers=bearer(reader))
    assert events.status_code == 403 and events.json()["error"]["code"] == "SCOPE_EXCEEDED"


def test_subscribing_beyond_read_scopes_is_refused(client: TestClient, db: Db) -> None:
    manager = new_token(client, admin(client, db), ["decisions:read", "webhooks:manage"])["token"]
    client.cookies.clear()
    body = {"url": HOOK, "event_types": ["DecisionApproved", "ClockBreached", "CommitmentDrifted"]}
    response = client.post("/v1/webhooks", json=body, headers=bearer(manager))
    assert response.status_code == 403
    assert response.json()["error"]["details"]["missing_scopes"] == ["clocks:read", "commitments:read"]
    with psycopg.connect(db.admin_url) as conn:
        count = conn.execute(
            "SELECT count(*) FROM webhook_subscription s JOIN api_token t USING (token_id)"
            " WHERE t.token_id = %s",
            (manager.split("_")[1],),
        ).fetchone()
    assert count == (0,)


def test_ssrf_targets_are_refused(client: TestClient, db: Db) -> None:
    manager = new_token(client, admin(client, db), ["decisions:read", "webhooks:manage"])["token"]
    client.cookies.clear()
    for url in ("https://127.0.0.1:9/x", "https://169.254.169.254/latest", "http://127.0.0.1:8701/x"):
        response = client.post(
            "/v1/webhooks", json={"url": url, "event_types": ["DecisionApproved"]}, headers=bearer(manager)
        )
        assert response.status_code == 422, url


def test_subscription_lifecycle_is_audited_and_secret_shown_once(client: TestClient, db: Db) -> None:
    manager = new_token(client, admin(client, db), ["decisions:read", "commitments:read", "webhooks:manage"])
    token, token_id = manager["token"], manager["token_id"]
    client.cookies.clear()
    events: list[WebhookType] = ["DecisionApproved", "CommitmentDrifted"]
    created = client.post("/v1/webhooks", json={"url": HOOK, "event_types": events}, headers=bearer(token))
    assert created.status_code == 201, created.text
    secret = created.headers["sgw-webhook-secret"]
    sub = created.json()
    assert secret.startswith("whsec_") and sub["secret_hint"] == secret[-4:] and secret not in created.text
    assert created.headers["cache-control"] == "no-store"
    sid = sub["subscription_id"]
    listed = client.get("/v1/webhooks", headers=bearer(token)).json()
    assert [s["subscription_id"] for s in listed] == [sid] and "secret" not in listed[0]
    rotated = client.post(f"/v1/webhooks/{sid}/rotate-secret?overlap_s=3600", headers=bearer(token))
    assert rotated.status_code == 200 and rotated.json()["secret"] != secret
    other = new_token(client, admin(client, db), ["decisions:read", "webhooks:manage"])["token"]
    client.cookies.clear()
    assert client.delete(f"/v1/webhooks/{sid}", headers=bearer(other)).status_code == 404
    assert client.get(f"/v1/webhooks/{sid}/deliveries", headers=bearer(other)).status_code == 404
    assert client.delete(f"/v1/webhooks/{sid}", headers=bearer(token)).status_code == 204
    assert client.get("/v1/webhooks", headers=bearer(token)).json() == []
    kinds = audit_kinds(db.admin_url, f"webhook_subscription:{sid}")
    assert [k for k, _ in kinds] == [
        "webhook_subscription.created",
        "webhook_subscription.secret_rotated",
        "webhook_subscription.deleted",
    ]
    assert all(p.get("token_id", token_id) == token_id for _, p in kinds)
    assert secret not in str(kinds) and rotated.json()["secret"] not in str(kinds)
    with psycopg.connect(db.admin_url) as conn:
        stored = conn.execute(
            "SELECT ciphertext FROM webhook_secret WHERE subscription_id = %s", (sid,)
        ).fetchall()
    assert len(stored) == 2 and all(secret.encode() not in bytes(r[0]) for r in stored)


def test_revoking_a_token_ends_access_and_disables_its_subscriptions(client: TestClient, db: Db) -> None:
    csrf = admin(client, db)
    created = new_token(client, csrf, ["decisions:read", "webhooks:manage"])
    token, token_id = created["token"], created["token_id"]
    sub = client.post(
        "/v1/webhooks", json={"url": HOOK, "event_types": ["DecisionApproved"]}, headers=bearer(token)
    )
    sid = sub.json()["subscription_id"]
    listed = client.get("/api/admin/tokens").json()
    assert token_id in {t["token_id"] for t in listed} and token not in str(listed)
    assert client.delete(f"/api/admin/tokens/{token_id}", headers=csrf).status_code == 204
    assert client.get("/v1/decisions", headers=bearer(token)).status_code == 401
    with psycopg.connect(db.admin_url) as conn:
        active = conn.execute(
            "SELECT active, disabled_reason FROM webhook_subscription WHERE subscription_id = %s", (sid,)
        ).fetchone()
    assert active == (False, "token_revoked")
    kinds = audit_kinds(db.admin_url, f"api_token:{token_id}")
    assert [k for k, _ in kinds] == ["api_token.created", "api_token.revoked"]
    assert kinds[1][1]["disabled_subscriptions"] == [sid]


def test_expired_token_is_refused(client: TestClient, db: Db) -> None:
    created = new_token(client, admin(client, db), ["decisions:read"])
    with psycopg.connect(db.admin_url, autocommit=True) as conn:
        conn.execute(
            "UPDATE api_token SET created_at = now() - interval '2 days',"
            " expires_at = now() - interval '1 second' WHERE token_id = %s",
            (created["token_id"],),
        )
    client.cookies.clear()
    assert client.get("/v1/decisions", headers=bearer(created["token"])).status_code == 401


def test_live_responses_conform_to_the_v1_document(client: TestClient, db: Db) -> None:
    import json

    import jsonschema

    from sgw.integrations import openapi

    doc = json.loads(openapi.DOCUMENT.read_text(encoding="utf-8"))
    scopes = ["decisions:read", "commitments:read", "webhooks:manage"]
    token = new_token(client, admin(client, db), scopes)["token"]
    client.cookies.clear()
    created = client.post(
        "/v1/webhooks", json={"url": HOOK, "event_types": ["DecisionApproved"]}, headers=bearer(token)
    )
    sid = created.json()["subscription_id"]
    calls = [
        ("post", "/v1/webhooks", created, "201"),
        ("get", "/v1/decisions", client.get("/v1/decisions", headers=bearer(token)), "200"),
        (
            "get",
            "/v1/decisions/{decision_case_id}",
            client.get(f"/v1/decisions/{golden.CASE_CREWS}", headers=bearer(token)),
            "200",
        ),
        ("get", "/v1/commitments", client.get("/v1/commitments", headers=bearer(token)), "200"),
        ("get", "/v1/webhooks", client.get("/v1/webhooks", headers=bearer(token)), "200"),
        (
            "get",
            "/v1/webhooks/{subscription_id}/deliveries",
            client.get(f"/v1/webhooks/{sid}/deliveries", headers=bearer(token)),
            "200",
        ),
        (
            "post",
            "/v1/webhooks/{subscription_id}/rotate-secret",
            client.post(f"/v1/webhooks/{sid}/rotate-secret", headers=bearer(token)),
            "200",
        ),
        (
            "get",
            "/v1/decisions/{decision_case_id}",
            client.get("/v1/decisions/DC-NONE", headers=bearer(token)),
            "404",
        ),
    ]
    for method, path, response, status in calls:
        assert str(response.status_code) == status, (path, response.text)
        spec = doc["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
        jsonschema.Draft202012Validator({**spec, "components": doc["components"]}).validate(response.json())
