"""Read-only admin views: users and their functions, what each may approve, and the per-node LLM
configuration. Nothing here writes; role changes stay T2 proposals.

- users: `app_user` (K18 seed), as K3 `Me` rows without a session (`step_up_valid_until` null);
- approval rights: `authority_rule` (the T2/T3 approver and escalation functions per action type) joined
  to the user's functions, only for users with `can_approve`;
- AI configuration: `src/sgw/agent/llm_nodes.yaml` (K14) validated by its schema; the custom tools a node may
  call come from the copilot tool binding (K5). Prompts, keys and schemas are never read.
"""

from __future__ import annotations

from typing import Any, Literal

import yaml
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.contracts.api_models import AiConfig, AiNodeConfig, AiNodeEval, ApprovalRight, Me, UserApprovalRights
from sgw.contracts.llm_nodes import validate_nodes_yaml
from sgw.contracts.vocab import ActionType, ApprovalFunction, Domain, Tier

AI_CONFIG_SOURCE = "src/sgw/agent/llm_nodes.yaml"

_USERS = """
SELECT user_id, display_name, function::text AS function, roles, regions, domains::text[] AS domains,
       functions::text[] AS functions, can_approve, break_glass_eligible
FROM app_user
ORDER BY user_id
"""

_RULES = """
SELECT action_type, tier::text AS tier, approver_functions, escalated_functions
FROM authority_rule
ORDER BY action_type
"""


async def _rows(conn: AsyncConnection[Any], sql: str) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        return list(await cur.fetchall())


async def users(conn: AsyncConnection[Any], demo_mode: bool) -> list[Me]:
    return [
        Me(
            user_id=r["user_id"],
            display_name=r["display_name"],
            function=ApprovalFunction(r["function"]),
            roles=list(r["roles"] or []),
            regions=list(r["regions"] or []),
            domains=[Domain(d) for d in r["domains"] or []],
            step_up_valid_until=None,
            demo_mode=demo_mode,
        )
        for r in await _rows(conn, _USERS)
    ]


async def approval_rights(conn: AsyncConnection[Any]) -> list[UserApprovalRights]:
    rules = await _rows(conn, _RULES)
    out: list[UserApprovalRights] = []
    for u in await _rows(conn, _USERS):
        held = set(u["functions"] or []) | {u["function"]}
        rights: list[ApprovalRight] = []
        if u["can_approve"]:
            for r in rules:
                role: Literal["approver", "escalation_approver"]
                if held & set(r["approver_functions"]):
                    role = "approver"
                elif held & set(r["escalated_functions"]):
                    role = "escalation_approver"
                else:
                    continue
                rights.append(
                    ApprovalRight(action_type=ActionType(r["action_type"]), tier=Tier(r["tier"]), role=role)
                )
        out.append(
            UserApprovalRights(
                user_id=u["user_id"],
                function=ApprovalFunction(u["function"]),
                can_approve=bool(u["can_approve"]),
                break_glass_eligible=bool(u["break_glass_eligible"]),
                may_approve=rights,
            )
        )
    return out


def node_tools() -> dict[str, list[str]]:
    from sgw.agent.copilot.investigate import NODE as INVESTIGATE
    from sgw.agent.copilot.tools import BOUND_TOOLS

    return {INVESTIGATE: list(BOUND_TOOLS)}


def ai_config() -> AiConfig:
    from sgw.agent.nodes.llm import NODES_FILE

    parsed = validate_nodes_yaml(yaml.safe_load(NODES_FILE.read_text(encoding="utf-8")))
    tools = node_tools()
    return AiConfig(
        version=parsed.version,
        source=AI_CONFIG_SOURCE,
        nodes=[
            AiNodeConfig(
                node=n.node,
                model=n.model,
                effort=n.effort,
                max_tokens=n.max_tokens,
                prompt_version=n.prompt_version,
                class_ceiling=n.class_ceiling,
                citations=n.citations,
                routes=list(n.routes),
                allowed_tools=tools.get(n.node, []),
                tool_types=list(n.tool_types),
                eval_result=AiNodeEval(
                    report=n.eval_result.report,
                    metric=n.eval_result.metric,
                    value_ppm=n.eval_result.value_ppm,
                    passed=n.eval_result.passed,
                )
                if n.eval_result
                else None,
            )
            for n in parsed.nodes
        ],
    )
