"""Sessions, CSRF, persona switch and scenario clock over a real socket through the repository Caddyfile."""

from __future__ import annotations

import httpx
import psycopg
import pytest

from sgw.api.audit_log import GENESIS_HASH, record_hash
from sgw.contracts.api_models import Me, ScenarioState
from sgw.contracts.approval import canonical_json, sha256_hex

from .sse_testkit import LOGIN_USER_BURST, CaddyPorts, ScratchDb, expect

pytestmark = pytest.mark.slow


def _login(client: httpx.Client, user: str, password: str) -> httpx.Response:
    return client.post("/api/auth/login", json={"user_id": user, "password": password})


def _csrf(client: httpx.Client) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["sgw_csrf"]}


def test_login_sets_strict_httponly_cookie_and_me_works(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        assert c.get("/api/me").status_code == 401
        bad = _login(c, "ic_01", "wrong-password")
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "INVALID_CREDENTIALS"
        r = _login(c, "ic_01", scratch_db.password)
        assert r.status_code == 200, r.text
        cookies = r.headers.get_list("set-cookie")
        session = next(h for h in cookies if h.startswith("sgw_session="))
        assert "HttpOnly" in session and "SameSite=strict" in session and "Path=/" in session
        csrf = next(h for h in cookies if h.startswith("sgw_csrf="))
        assert "HttpOnly" not in csrf
        me = Me.model_validate(c.get("/api/me").json())
        assert me.user_id == "ic_01" and me.demo_mode and me.step_up_valid_until is not None
        assert r.headers["cache-control"] == "no-store"
        assert "x-request-id" in r.headers
        assert "content-security-policy" in r.headers, "Caddy security headers apply to /api"


def test_writes_need_csrf_and_cross_site_is_refused(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        expect(_login(c, "ops_dm_01", scratch_db.password), 200)
        no = c.post("/api/scenario", json={"action": "pause"})
        assert no.status_code == 403 and no.json()["error"]["code"] == "CSRF_FAILED"
        cross = c.post(
            "/api/scenario", json={"action": "pause"}, headers={**_csrf(c), "Sec-Fetch-Site": "cross-site"}
        )
        assert cross.status_code == 403 and cross.json()["error"]["code"] == "CROSS_SITE"
        ok = c.post("/api/scenario", json={"action": "pause"}, headers=_csrf(c))
        assert ok.status_code == 200, ok.text


def test_auditor_is_read_only(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        assert _login(c, "audit_01", scratch_db.password).status_code == 200
        assert c.get("/api/scenario").status_code == 200
        r = c.post("/api/scenario", json={"action": "play"}, headers=_csrf(c))
        assert r.status_code == 403 and r.json()["error"]["code"] == "READ_ONLY_ROLE"


def test_persona_switch_revokes_old_session_and_is_audited(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        expect(_login(c, "ic_01", scratch_db.password), 200)
        old = c.cookies["sgw_session"]
        r = _login(c, "wtr_lead_01", scratch_db.password)
        assert r.status_code == 200
        assert r.headers["x-sgw-persona-switched-from"] == "ic_01"
        assert c.get("/api/me").json()["user_id"] == "wtr_lead_01"
    with httpx.Client(base_url=caddy.site_url, cookies={"sgw_session": old}) as stale:
        assert stale.get("/api/me").status_code == 401
    with psycopg.connect(scratch_db.admin_url) as conn:
        row = conn.execute(
            "SELECT actor_id, payload FROM audit_event WHERE kind = 'persona_switched'"
            " ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "wtr_lead_01" and row[1]["from_user_id"] == "ic_01"
        flagged = conn.execute(
            "SELECT demo_switch FROM session WHERE user_id = 'wtr_lead_01' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        assert flagged == (True,)


def test_step_up_and_logout(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        expect(_login(c, "log_01", scratch_db.password), 200)
        assert c.post("/api/auth/step-up", json={"password": "nope"}, headers=_csrf(c)).status_code == 401
        up = c.post("/api/auth/step-up", json={"password": scratch_db.password}, headers=_csrf(c))
        assert up.status_code == 200 and up.json()["step_up_valid_until"]
        assert c.post("/api/auth/logout", headers=_csrf(c)).status_code == 204
        assert c.get("/api/me").status_code == 401


def test_scenario_bookmark_round_trip(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        expect(_login(c, "ic_01", scratch_db.password), 200)
        st = ScenarioState.model_validate(
            c.post("/api/scenario", json={"action": "bookmark", "bookmark": "H0-24"}, headers=_csrf(c)).json()
        )
        assert st.scenario_time.isoformat().startswith("2024-09-26T03:10")
        bad = c.post(
            "/api/scenario",
            json={"action": "seek", "scenario_time": "2030-01-01T00:00:00Z"},
            headers=_csrf(c),
        )
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "SCENARIO_COMMAND_INVALID"


def test_audit_chain_is_linked_and_hashes_recompute(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with psycopg.connect(scratch_db.admin_url) as conn:
        rows = conn.execute(
            "SELECT stream, seq, event_key, occurred_at, actor_type, actor_id, kind, subject, payload_hash,"
            " payload, prev_hash, hash FROM audit_event ORDER BY seq"
        ).fetchall()
    assert len(rows) >= 5
    prev = GENESIS_HASH
    for i, r in enumerate(rows, 1):
        assert r[1] == i and r[10] == prev
        assert r[8] == sha256_hex(canonical_json(r[9]))
        from sgw.contracts.base import utc_iso

        header = {
            "stream": r[0],
            "seq": r[1],
            "event_key": r[2],
            "occurred_at": utc_iso(r[3]),
            "actor_type": r[4],
            "actor_id": r[5],
            "kind": r[6],
            "subject": r[7],
            "payload_hash": r[8],
            "prev_hash": r[10],
        }
        assert r[11] == record_hash(header)
        prev = r[11]


def test_step_up_is_per_session_not_per_user(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    from sgw.api.security import token_hash

    with httpx.Client(base_url=caddy.site_url) as a, httpx.Client(base_url=caddy.site_url) as b:
        expect(_login(a, "ops_dm_02", scratch_db.password), 200)
        expect(_login(b, "ops_dm_02", scratch_db.password), 200)
        up = a.post("/api/auth/step-up", json={"password": scratch_db.password}, headers=_csrf(a))
        assert up.status_code == 200
        with psycopg.connect(scratch_db.admin_url) as conn:
            rows = dict(
                conn.execute(
                    "SELECT token_hash, step_up_at FROM session WHERE token_hash = ANY(%s)",
                    ([token_hash(a.cookies["sgw_session"]), token_hash(b.cookies["sgw_session"])],),
                ).fetchall()
            )
        assert rows[token_hash(a.cookies["sgw_session"])] > rows[token_hash(b.cookies["sgw_session"])]


def test_scenario_control_is_limited_to_command_operations_presenter(
    scratch_db: ScratchDb, caddy: CaddyPorts
) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        expect(_login(c, "wtr_lead_01", scratch_db.password), 200)
        assert c.get("/api/scenario").status_code == 200
        r = c.post("/api/scenario", json={"action": "pause"}, headers=_csrf(c))
        assert r.status_code == 403 and r.json()["error"]["code"] == "SCENARIO_CONTROL_DENIED"


def test_login_attempts_are_rate_limited_per_user(scratch_db: ScratchDb, caddy: CaddyPorts) -> None:
    with httpx.Client(base_url=caddy.site_url) as c:
        codes = [_login(c, "rl_probe_01", "wrong").status_code for _ in range(LOGIN_USER_BURST)]
        assert set(codes) == {401}
        r = _login(c, "rl_probe_01", "wrong")
        assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
        assert int(r.headers["retry-after"]) >= 1
        assert _login(c, "exec_01", scratch_db.password).status_code == 200, "other users are not locked out"
