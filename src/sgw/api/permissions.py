"""What a person may do (K3 `getMyPermissions`), from the constants and tables the write routes check, so the
UI never offers a control the API refuses. A read-only role gets no write permission (the `Writer`
dependency refuses it before any rule runs)."""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection

from sgw.api.readmodels import readiness
from sgw.api.routers.admin import ADMIN_ROLES
from sgw.api.routers.ops import PIPELINE_FUNCTIONS
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import Permissions
from sgw.contracts.vocab import ApprovalFunction
from sgw.dispatch.policy import ACTOR_ROLES
from sgw.ops import levels

RUN_CANCEL_FUNCTIONS = frozenset({ApprovalFunction.PLATFORM, ApprovalFunction.DATA})


def is_admin(user: AuthUser) -> bool:
    return user.function is ApprovalFunction.PLATFORM or bool(ADMIN_ROLES.intersection(user.roles))


async def kill_roles(conn: AsyncConnection[Any]) -> frozenset[str]:
    cur = await conn.execute("SELECT role FROM ops_kill_role")
    return frozenset(str(r[0]) for r in await cur.fetchall())


async def permissions(conn: AsyncConnection[Any], user: AuthUser) -> Permissions:
    roles = frozenset(user.roles)
    admin = is_admin(user)
    if user.read_only:
        return Permissions(
            stop_raise=False,
            stop_restore=False,
            mode_raise=False,
            mode_lower=False,
            crew_dispatch=False,
            pipeline_run=False,
            agent_run_cancel=False,
            admin=admin,
        )
    may_trigger = bool(roles & await kill_roles(conn))
    mode_lower = user.function in levels.MODE_LOWER_FUNCTIONS
    return Permissions(
        stop_raise=may_trigger,
        stop_restore=user.function in levels.RESTORE_FUNCTIONS,
        mode_raise=may_trigger or bool(roles & levels.MODE_RAISE_ROLES) or mode_lower,
        mode_lower=mode_lower,
        crew_dispatch=bool(roles & frozenset(ACTOR_ROLES)),
        pipeline_run=user.function in PIPELINE_FUNCTIONS,
        agent_run_cancel=user.function in RUN_CANCEL_FUNCTIONS,
        admin=admin,
        readiness_record=[i.item_id for i in readiness.readiness() if i.owner_function is user.function],
    )
