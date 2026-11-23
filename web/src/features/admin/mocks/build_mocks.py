"""Regenerates the admin feature mocks: `uv run python <this file>` from the repo root."""

import json
import re
from pathlib import Path

import yaml

from sgw.api.readmodels.admin import ai_config

OUT = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[5]

RULES = re.compile(r"\('(\w+)', '(T\d)', '\{([\w,]*)\}', '\{([\w,]*)\}'\)")


def rules() -> list[tuple[str, str, set[str], set[str]]]:
    sql = (ROOT / "db/migrations/4800_authority_write_guard.sql").read_text()
    sql += (ROOT / "db/migrations/4802_authority_rule_policy_change.sql").read_text()
    return [
        (a, t, set(filter(None, ap.split(","))), set(filter(None, es.split(","))))
        for a, t, ap, es in RULES.findall(sql)
    ]


def main() -> None:
    seed = yaml.safe_load((ROOT / "data/seed/users.yaml").read_text())["users"]
    users = [
        {
            "user_id": u["user_id"],
            "display_name": u["display_name"],
            "function": u["function"],
            "roles": u["roles"],
            "regions": u["regions"],
            "domains": u["domains"],
            "step_up_valid_until": None,
            "demo_mode": True,
        }
        for u in seed
    ]
    rights = []
    for u in seed:
        held = {u["function"], *u.get("functions", [])}
        may = []
        if u.get("can_approve"):
            for action, tier, approvers, escalated in rules():
                if held & approvers:
                    may.append({"action_type": action, "tier": tier, "role": "approver"})
                elif held & escalated:
                    may.append({"action_type": action, "tier": tier, "role": "escalation_approver"})
        rights.append(
            {
                "user_id": u["user_id"],
                "function": u["function"],
                "can_approve": bool(u.get("can_approve")),
                "break_glass_eligible": bool(u.get("break_glass_eligible")),
                "may_approve": may,
            }
        )
    (OUT / "users.json").write_text(json.dumps(users, indent=2) + "\n")
    (OUT / "rights.json").write_text(json.dumps(rights, indent=2) + "\n")
    (OUT / "ai-config.json").write_text(ai_config().model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    main()
