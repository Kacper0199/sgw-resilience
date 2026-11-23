"""Cookie sessions, login, step-up and the demo persona switch (DC-41).

- A login is a real password check and counts as a step-up for `STEP_UP_TTL_S` (5 min).
- With `DEMO_MODE=1`, logging in as another user while a session is open is a persona switch: the old session
  is revoked, the new one is flagged `demo_switch`, and the audit records `persona_switched` (from, to).
- Every login, failed login, logout, step-up and switch is an audit record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.api import audit_log
from sgw.api.errors import Unauthenticated
from sgw.api.security import new_session_token, token_hash, verify_password
from sgw.api.settings import ApiSettings
from sgw.contracts.api_models import Me
from sgw.contracts.vocab import ApprovalFunction, Domain

READ_ONLY_ROLES = frozenset({"auditor"})


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    display_name: str
    function: ApprovalFunction
    roles: tuple[str, ...]
    regions: tuple[str, ...]
    domains: tuple[Domain, ...]
    step_up_at: datetime | None
    session_hash: str
    demo_switch: bool

    @property
    def role(self) -> str:
        return self.roles[0] if self.roles else self.function.value

    @property
    def read_only(self) -> bool:
        return bool(READ_ONLY_ROLES.intersection(self.roles))

    def step_up_valid_until(self, now: datetime, ttl_s: int) -> datetime | None:
        if self.step_up_at is None:
            return None
        until = self.step_up_at + timedelta(seconds=ttl_s)
        return until if until > now else None

    def me(self, settings: ApiSettings, now: datetime) -> Me:
        return Me(
            user_id=self.user_id,
            display_name=self.display_name,
            function=self.function,
            roles=list(self.roles),
            regions=list(self.regions),
            domains=list(self.domains),
            step_up_valid_until=self.step_up_valid_until(now, settings.step_up_ttl_s),
            demo_mode=settings.demo_mode,
        )


_USER_COLUMNS = "u.user_id, u.display_name, u.function, u.roles, u.regions, u.domains, s.step_up_at"


def _auth_user(row: dict[str, Any], session_hash: str, demo_switch: bool) -> AuthUser:
    return AuthUser(
        user_id=row["user_id"],
        display_name=row["display_name"],
        function=ApprovalFunction(row["function"]),
        roles=tuple(row["roles"] or ()),
        regions=tuple(row["regions"] or ()),
        domains=tuple(Domain(d) for d in _text_array(row["domains"])),
        step_up_at=row["step_up_at"],
        session_hash=session_hash,
        demo_switch=demo_switch,
    )


def _text_array(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        inner = value.strip("{}")
        return [v for v in inner.split(",") if v]
    return [str(v) for v in value]


async def resolve(conn: AsyncConnection[Any], token: str | None, now: datetime) -> AuthUser | None:
    return await resolve_by_hash(conn, token_hash(token), now) if token else None


async def _password_hash(conn: AsyncConnection[Any], user_id: str) -> str | None:
    cur = await conn.execute("SELECT password_hash FROM app_user WHERE user_id = %s", (user_id,))
    row = await cur.fetchone()
    return str(row[0]) if row and row[0] else None


VERIFY_SLOTS = 4
_verify_slots = asyncio.Semaphore(VERIFY_SLOTS)


async def _check_password(conn: AsyncConnection[Any], user_id: str, password: str) -> bool:
    """Argon2 runs in a worker thread; at most `VERIFY_SLOTS` at once, so a flood cannot pin the CPU."""
    stored = await _password_hash(conn, user_id)
    async with _verify_slots:
        return await asyncio.to_thread(verify_password, stored, password)


@dataclass(frozen=True)
class LoginResult:
    user: AuthUser
    token: str
    switched_from: str | None


async def login(
    conn: AsyncConnection[Any],
    settings: ApiSettings,
    *,
    user_id: str,
    password: str,
    current: AuthUser | None,
    now: datetime,
) -> LoginResult:
    if not await _check_password(conn, user_id, password):
        await audit_log.append(
            conn,
            kind="login_failed",
            actor_type="system",
            actor_id="api",
            subject=f"user:{user_id[:64]}",
            payload={"user_id": user_id[:64]},
            occurred_at=now,
        )
        raise Unauthenticated("invalid user id or password", code="INVALID_CREDENTIALS")
    switched_from = current.user_id if current and current.user_id != user_id and settings.demo_mode else None
    if current is not None:
        await conn.execute("DELETE FROM session WHERE token_hash = %s", (current.session_hash,))
    token = new_session_token()
    await conn.execute(
        "INSERT INTO session (token_hash, user_id, created_at, expires_at, demo_switch, step_up_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (
            token_hash(token),
            user_id,
            now,
            now + timedelta(seconds=settings.session_ttl_s),
            switched_from is not None,
            now,
        ),
    )
    if switched_from:
        await audit_log.append(
            conn,
            kind="persona_switched",
            actor_type="user",
            actor_id=user_id,
            subject=f"user:{user_id}",
            payload={"from_user_id": switched_from, "to_user_id": user_id, "demo_mode": True},
            occurred_at=now,
        )
    else:
        await audit_log.append(
            conn,
            kind="login",
            actor_type="user",
            actor_id=user_id,
            subject=f"user:{user_id}",
            payload={"user_id": user_id, "demo_mode": settings.demo_mode},
            occurred_at=now,
        )
    user = await resolve(conn, token, now)
    assert user is not None
    return LoginResult(user, token, switched_from)


async def logout(conn: AsyncConnection[Any], user: AuthUser, now: datetime) -> None:
    await conn.execute("DELETE FROM session WHERE token_hash = %s", (user.session_hash,))
    await audit_log.append(
        conn,
        kind="logout",
        actor_type="user",
        actor_id=user.user_id,
        subject=f"user:{user.user_id}",
        payload={"user_id": user.user_id},
        occurred_at=now,
    )


async def step_up(conn: AsyncConnection[Any], user: AuthUser, password: str, now: datetime) -> AuthUser:
    if not await _check_password(conn, user.user_id, password):
        await audit_log.append(
            conn,
            kind="step_up_failed",
            actor_type="user",
            actor_id=user.user_id,
            subject=f"user:{user.user_id}",
            payload={"user_id": user.user_id},
            occurred_at=now,
        )
        raise Unauthenticated("password did not match", code="STEP_UP_FAILED")
    await conn.execute("UPDATE session SET step_up_at = %s WHERE token_hash = %s", (now, user.session_hash))
    await audit_log.append(
        conn,
        kind="step_up",
        actor_type="user",
        actor_id=user.user_id,
        subject=f"user:{user.user_id}",
        payload={"user_id": user.user_id},
        occurred_at=now,
    )
    refreshed = await resolve_by_hash(conn, user.session_hash, now)
    assert refreshed is not None
    return refreshed


async def resolve_by_hash(conn: AsyncConnection[Any], digest: str, now: datetime) -> AuthUser | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {_USER_COLUMNS}, s.demo_switch FROM session s JOIN app_user u USING (user_id)"  # noqa: S608
            " WHERE s.token_hash = %s AND s.expires_at > %s",
            (digest, now),
        )
        row = await cur.fetchone()
    return _auth_user(row, digest, bool(row["demo_switch"])) if row else None
