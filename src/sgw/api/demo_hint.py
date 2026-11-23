"""The sign-in page's demo password hint: the public demo value is offered only when it is true,
that is when every account with a password in the database verifies against it. Hashes are read on each
call (cheap); Argon2 runs again only when they change, for example after a seed or a demo-moment load."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from psycopg import AsyncConnection

from sgw.api.security import verify_password
from sgw.contracts.identities import PUBLIC_DEMO_PASSWORD

_verdicts: dict[str, bool] = {}


def _all_match(hashes: list[str]) -> bool:
    return bool(hashes) and all(verify_password(h, PUBLIC_DEMO_PASSWORD) for h in hashes)


async def public_demo_password(conn: AsyncConnection[Any]) -> str | None:
    cur = await conn.execute(
        "SELECT password_hash FROM app_user WHERE password_hash IS NOT NULL ORDER BY user_id"
    )
    hashes = [str(row[0]) for row in await cur.fetchall()]
    key = hashlib.sha256("\n".join(hashes).encode()).hexdigest()
    if key not in _verdicts:
        _verdicts.clear()
        _verdicts[key] = await asyncio.to_thread(_all_match, hashes)
    return PUBLIC_DEMO_PASSWORD if _verdicts[key] else None
