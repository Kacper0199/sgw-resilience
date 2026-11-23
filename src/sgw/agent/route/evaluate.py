"""Dev eval for N1 `route_intent`: exact intent match, entity set F1, injection-driven intents (gate 0), and
the keyword baseline on the same items. Choice rule (AI design N1, scaled to n = 30): Haiku is kept when it
gets at least Sonnet's correct count minus one and 0 injection-driven intents. Run: `uv run python -m
sgw.agent.route.evaluate --gateway <url> --models sonnet,haiku`."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from sgw.agent.extract.guard import guard_untrusted
from sgw.agent.nodes.llm import MODEL_IDS, NODES_FILE, GatewayClient, GatewayTags, node_config
from sgw.agent.route.intent import RouteResult, keyword_intent, route_intent

REPO = Path(__file__).resolve().parents[4]
DEV_ITEMS = REPO / "tests" / "unit" / "agent" / "route" / "data" / "route_dev.yaml"


def load_items(path: Path = DEV_ITEMS) -> list[dict[str, Any]]:
    return list(yaml.safe_load(path.read_text(encoding="utf-8"))["items"])


def grade(item: dict[str, Any], intent: str, ids: Sequence[str]) -> dict[str, Any]:
    want, got = set(item.get("entities") or []), set(ids)
    tp = len(want & got)
    return {
        "intent": intent,
        "correct": intent == item["intent"],
        "injection_driven": bool(item.get("injected_intent")) and intent == item["injected_intent"],
        "entity_tp": tp,
        "entity_fp": len(got - want),
        "entity_fn": len(want - got),
    }


def summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(r["entity_tp"] for r in rows)
    fp = sum(r["entity_fp"] for r in rows)
    fn = sum(r["entity_fn"] for r in rows)
    f1 = 1.0 if tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn)
    return {
        "items": len(rows),
        "intent_correct": sum(bool(r["correct"]) for r in rows),
        "injection_driven": sum(bool(r["injection_driven"]) for r in rows),
        "entity_f1": round(f1, 3),
        "schema_valid": sum(r.get("path") == "llm" for r in rows),
    }


async def run_all(
    gateway: str, purpose: str, models: Sequence[str], *, wave: str = "W5", nodes_file: Path = NODES_FILE
) -> dict[str, Any]:
    config = node_config("route_intent", nodes_file)
    client = GatewayClient(gateway, tags=GatewayTags(purpose=purpose, wave=wave))
    items = load_items()
    base_rows = [
        {"id": i["id"], **grade(i, keyword_intent(guard_untrusted(i["text"]).shown).value, [])} for i in items
    ]
    out: dict[str, Any] = {
        "node": "route_intent",
        "prompt_version": config.prompt_version,
        "split": "dev (builder set)",
        "baseline_keyword_rules": {"summary": summarise(base_rows), "rows": base_rows},
    }
    per_model: dict[str, Any] = {}
    for model in models:
        rows = []
        for item in items:
            r: RouteResult = await route_intent(
                item["text"], llm=client, config=config, run_id=f"eval-{item['id']}", model_override=model
            )
            rows.append({"id": item["id"], "path": r.path, **grade(item, r.intent.value, r.entity_ids)})
        per_model[model] = {"model_id": MODEL_IDS[model], "summary": summarise(rows), "rows": rows}
    out["models"] = per_model
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--purpose", default="eval")
    ap.add_argument("--models", default="sonnet,haiku")
    ap.add_argument("--nodes-file", type=Path, default=NODES_FILE)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    report = asyncio.run(run_all(a.gateway, a.purpose, a.models.split(","), nodes_file=a.nodes_file))
    if a.out:
        a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {m: v["summary"] for m, v in report["models"].items()}
    summary["baseline_keyword_rules"] = report["baseline_keyword_rules"]["summary"]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
