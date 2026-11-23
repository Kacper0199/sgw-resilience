"""Which tools a role may call: the copilot mirrors what the role's pages show.

A role sees the domains its seeded people work in (K18 `data/seed/users.yaml`, union per function), as the
REST reads do for the water register (`WATER_DOMAIN_REQUIRED`). Electric field tools (outages, crews, ETR,
outage surges, damage photos) need the electric domain; water tools (water status, A7/A8 anomalies) need the
water domain; the cross-domain reads (risk, forecasts, what-if, feed health, decisions, readiness, procedures,
decision cases) are open to every signed-in role. A function without seeded people (communications) gets
only the cross-domain reads. Operations (the duty manager) also reads water status in Ask: the duty desk runs
both services through the storm (user decision Q-07 A, 2026-11-22 review)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from sgw.contracts.identities import load_users
from sgw.contracts.tools import MODEL_VISIBLE_TOOLS
from sgw.contracts.vocab import ApprovalFunction, Domain

USERS_FILE = Path(__file__).resolve().parents[4] / "data" / "seed" / "users.yaml"
TOOL_DOMAIN: dict[str, Domain] = {
    "get_outages": Domain.ELECTRIC,
    "get_crews": Domain.ELECTRIC,
    "get_etr": Domain.ELECTRIC,
    "list_outage_surges": Domain.ELECTRIC,
    "get_damage_photos": Domain.ELECTRIC,
    "get_water_status": Domain.WATER,
    "list_anomalies": Domain.WATER,
}

ASK_EXTRA_DOMAINS: dict[ApprovalFunction, frozenset[Domain]] = {
    ApprovalFunction.OPERATIONS: frozenset({Domain.WATER}),
}
EXTRA = {"on": True}
"""The frozen R29 evals switch the R34 additions off (the extra domains, the count of the decisions a code
list leaves out), so they replay the requests they were measured on (their CLIs and tests set it; nothing
else does)."""


@cache
def function_domains() -> dict[ApprovalFunction, frozenset[Domain]]:
    found: dict[ApprovalFunction, set[Domain]] = {f: set() for f in ApprovalFunction}
    for user in load_users(USERS_FILE).users:
        found[user.function].update(user.domains)
    return {f: frozenset(d) for f, d in found.items()}


def may_call(role: ApprovalFunction, tool: str) -> bool:
    if tool not in MODEL_VISIBLE_TOOLS:
        return False
    domain = TOOL_DOMAIN.get(tool)
    extra = ASK_EXTRA_DOMAINS.get(role, frozenset()) if EXTRA["on"] else frozenset()
    return domain is None or domain in function_domains()[role] | extra


def tools_for(role: ApprovalFunction) -> tuple[str, ...]:
    return tuple(t for t in MODEL_VISIBLE_TOOLS if may_call(role, t))
