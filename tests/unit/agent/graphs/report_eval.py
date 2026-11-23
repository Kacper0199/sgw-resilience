"""Per-node selection eval for etr_brief, sitrep and after_action_summary (provisional for WP-29).

Four dev cases per node (different evidence), each run through its graph against a gateway, graded by code:
the text passed the D-073 verifier on the LLM path (no M2 fallback) and used the slots a reader needs. Run
against a record gateway to measure (`--purpose eval`), or a replay gateway to re-grade keyless.

    uv run python -m tests.unit.agent.graphs.report_eval --gateway http://127.0.0.1:8625 --models sonnet haiku
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sgw.agent.nodes.llm import GatewayClient, GatewayTags
from sgw.agent.render.evidence import EvidenceBundle
from sgw.models.restoration.publish import EtrEstimate
from sgw.reports import sources
from sgw.reports.after_action import AfterActionReview, BreakGlassUse, ChainCheck

from . import reports_testkit as rk

OUT = rk.REPO / "data" / "artefacts" / "evals" / "report_node_eval.json"
REPEATED = re.compile(r"\b([A-Za-z]{3,}) \1\b", re.IGNORECASE)
NODE_OF = {"etr": "etr_brief", "sitrep": "sitrep", "after_action": "after_action_summary"}


@dataclass(frozen=True)
class Case:
    case_id: str
    graph: str
    deps: dict[str, Any] = field(default_factory=dict)


def _h0() -> list[EtrEstimate]:
    return sources.load_estimates(rk.DATA / "etr_story_h0.jsonl")


def _uncalibrated() -> list[EtrEstimate]:
    return [e.model_copy(update={"calibrated": False}) for e in rk.estimates()]


def _review(
    mutate: Callable[[AfterActionReview], AfterActionReview],
) -> Callable[[datetime], AfterActionReview]:
    return lambda at: mutate(rk.fixed_review(at))


def _broken(r: AfterActionReview) -> AfterActionReview:
    chain = ChainCheck(
        ok=False, checked_to_seq=42, first_bad_seq=31, signed_head_seq=30, trusted_to_seq=30, problems=["x"]
    )
    return r.model_copy(update={"chain": chain})


def _clean(r: AfterActionReview) -> AfterActionReview:
    met = r.clocks[0]
    return r.model_copy(update={"clocks": [met], "break_glass": []})


def _worse(r: AfterActionReview) -> AfterActionReview:
    undecided = rk.clock(
        "DC-D2-CREWS-AIK",
        "Pre-position crews at Sandhill and Millpond yards before tropical-storm winds",
        "D2",
        "2024-09-26T09:20:00+00:00",
        "missed",
    )
    bg: BreakGlassUse = r.break_glass[0].model_copy(
        update={"status": "overdue_unsigned", "cosigned_by": None, "cosigned_at": None}
    )
    return r.model_copy(update={"clocks": [undecided, r.clocks[1]], "break_glass": [bg]})


SECOND_CLOCK = rk.clock(
    "DC-D2-CREWS-AIK",
    "Pre-position crews at Sandhill and Millpond yards before tropical-storm winds",
    "D2",
    "2024-09-28T22:00:00+00:00",
    "open",
)

CASES = [
    Case("etr-story-h24", "etr"),
    Case("etr-story-h0", "etr", {"estimates": _h0, "issue_offset_h": 0.0}),
    Case("etr-uncalibrated-h24", "etr", {"estimates": _uncalibrated}),
    Case("etr-story-h24-nopolicy", "etr", {"policy_evidence": False}),
    Case("sitrep-story", "sitrep"),
    Case(
        "sitrep-early-no-etr",
        "sitrep",
        {
            "estimates": None,
            "as_of": datetime(2024, 9, 27, 6, 0, tzinfo=UTC),
            "open_clocks": lambda _at: [],
            "cosign_open": lambda: None,
        },
    ),
    Case(
        "sitrep-two-clocks",
        "sitrep",
        {"open_clocks": lambda _at: [rk.OPEN_CLOCK, SECOND_CLOCK], "cosign_open": lambda: 1},
    ),
    Case("sitrep-late", "sitrep", {"as_of": datetime(2024, 9, 30, 12, 0, tzinfo=UTC)}),
    Case("aa-story", "after_action"),
    Case("aa-broken-chain", "after_action", {"review": _review(_broken)}),
    Case("aa-clean", "after_action", {"review": _review(_clean)}),
    Case("aa-worse", "after_action", {"review": _review(_worse), "as_of": rk.REVIEW_AT + timedelta(hours=1)}),
]


def _needed(graph: str, bundle: EvidenceBundle) -> set[str]:
    items = bundle.items
    need: set[str] = set()
    for i in items:
        if graph == "etr" and i.kind == "etr_estimate":
            need |= {f"{i.id}.p50", f"{i.id}.p25", f"{i.id}.p75"}
        if graph == "etr" and i.kind == "etr_region":
            need.add(f"{i.id}.p50")
        if graph == "sitrep" and i.kind == "system_status":
            need |= {f"{i.id}.customers_out_now", f"{i.id}.restored_since_peak"}
        if graph == "sitrep" and i.kind == "etr_estimate":
            need.add(f"{i.id}.p50")
        if i.kind in ("decision_clock", "missed_clock"):
            need.add(f"{i.id}.decide_by")
        if graph == "after_action" and i.kind == "clock_outcomes":
            need |= {f"{i.id}.met", f"{i.id}.missed"}
        if graph == "after_action" and i.kind == "break_glass":
            need.add(f"{i.id}.uses")
        if graph == "after_action" and i.kind == "interruption_record":
            need.add(f"{i.id}.duration")
    return need


async def run_case(case: Case, client: Any, model: str) -> dict[str, Any]:
    node = NODE_OF[case.graph]
    task = rk.run_task(
        case.graph, client, run_id=f"eval-{case.case_id}-{model}", model_overrides={node: model}, **case.deps
    )
    await task.run()
    state = await task.state()
    n = state["narrative"]
    bundle = EvidenceBundle.model_validate(state["bundle"])
    used = {k.split(".", 1)[0] + "." + k.split(".", 1)[1] for k in n["slots_shown"]}
    missing = sorted(_needed(case.graph, bundle) - used) if n["path"] == "llm" else []
    failures = []
    if n["path"] != "llm":
        failures.append(f"m2:{n['reason']}")
        failures += n["violations"][:5]
    failures += [f"missing_slot:{m}" for m in missing]
    failures += [f"repeated_word:{m.group(0)}" for m in REPEATED.finditer(n["rendered"])]
    usage = n.get("usage") or {}
    return {
        "case": case.case_id,
        "node": node,
        "model": model,
        "passed": not failures,
        "failures": failures,
        "words": len(n["rendered"].split()),
        "output_tokens": usage.get("output_tokens"),
        "text": n["text"] if n["path"] == "llm" else None,
    }


async def main(gateway: str, models: list[str], purpose: str, out: Path, only: list[str] | None) -> None:
    client = GatewayClient(gateway, tags=GatewayTags(purpose=purpose, wave="W5"))
    rows = []
    for case in CASES:
        if only and case.case_id not in only:
            continue
        for model in models:
            row = await run_case(case, client, model)
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("case", "model", "passed", "failures")}))  # noqa: T201
    summary: dict[str, dict[str, str]] = {}
    for node in NODE_OF.values():
        for model in models:
            mine = [r for r in rows if r["node"] == node and r["model"] == model]
            if mine:
                summary.setdefault(node, {})[model] = f"{sum(r['passed'] for r in mine)}/{len(mine)}"
    doc = {
        "name": "report_node_eval",
        "label": "dev cases, code graders, n = 4 per node and model; a screen, not a significance claim",
        "summary": summary,
        "rows": rows,
    }
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", required=True)
    ap.add_argument("--models", nargs="+", default=["sonnet"])
    ap.add_argument("--purpose", default="eval")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    asyncio.run(main(a.gateway, a.models, a.purpose, a.out, a.only))
