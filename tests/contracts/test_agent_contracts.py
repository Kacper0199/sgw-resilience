from __future__ import annotations

from datetime import UTC, datetime

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from sgw.common import telemetry
from sgw.contracts import evidence, tools
from sgw.contracts.eval_report import EvalReport, MetricRow
from sgw.contracts.llm_nodes import LlmNodesFile, NodeConfig
from sgw.contracts.vocab import Classification, RunMode


def _props(schema: dict) -> set[str]:
    names = set(schema.get("properties", {}))
    for sub in schema.get("$defs", {}).values():
        names |= set(sub.get("properties", {}))
    return names


@pytest.mark.parametrize("name", tools.MODEL_VISIBLE_TOOLS)
def test_model_visible_args_never_carry_injected_context(name: str) -> None:
    _, args, _ = tools.TOOLS[name]
    assert not _props(args.model_json_schema()) & tools.FORBIDDEN_MODEL_ARGS


def test_tool_list_matches_x05() -> None:
    assert set(tools.MODEL_VISIBLE_TOOLS) == {
        "get_risk",
        "get_forecast",
        "get_outages",
        "get_crews",
        "get_water_status",
        "list_anomalies",
        "get_feed_health",
        "search_procedures",
        "get_decision_case",
        "run_what_if",
        "list_decisions",
        "get_readiness",
        "get_etr",
        "list_outage_surges",
        "get_damage_photos",
    }
    assert not tools.TOOLS["draft_proposal"][0].model_visible
    assert not tools.TOOLS["optimise_prepositioning"][0].model_visible
    assert all(
        meta.side_effect == "none" for meta, _, _ in (tools.TOOLS[n] for n in tools.MODEL_VISIBLE_TOOLS)
    )
    assert tools.TOOLS["search_procedures"][0].returns_search_results
    assert tools.TOOLS["search_procedures"][2].model_fields["type"].default == "search_result"
    assert set(tools.GRAPHS) == {"assess", "water_continuity", "etr", "sitrep", "after_action", "copilot"}


def test_slot_render_and_verifier() -> None:
    text = "The pump station decide-by is {E1.decide_by}; floor per SC R.61-58.7.E(7) at {E2.floor}."
    assert evidence.verify_text(text, {"E1", "E2"}) == []
    assert evidence.render(text, {"E1": {"decide_by": "04:10Z"}, "E2": {"floor": "25 psi"}}).endswith(
        "25 psi."
    )
    assert evidence.verify_text("Pressure is 24 psi at PS-17", {"E1"})
    assert evidence.verify_text("Hook up PS-17 first", {"E1"}), (
        "D-073: no PS-17 pattern; ids pass only by registry"
    )
    assert evidence.verify_text("{E9.value} rising", {"E1"}) == ["unknown evidence E9"]
    assert evidence.verify_text("Advisory issued 2024-09-26T15:00Z per SOP-WTR-4.2", set()) == []
    with pytest.raises(evidence.SlotError):
        evidence.render("{E3.p50}", {})


def test_llm_node_config_forbids_sampling_and_requires_effort() -> None:
    good = {
        "node": "answer_sop",
        "model": "sonnet",
        "effort": "medium",
        "max_tokens": 2048,
        "prompt_version": "v1",
        "class_ceiling": "C2",
        "citations": True,
    }
    LlmNodesFile.model_validate({"version": 1, "nodes": [good]})
    for bad in ({"temperature": 0.2}, {"top_p": 0.9}, {"top_k": 5}):
        with pytest.raises(ValidationError):
            NodeConfig.model_validate({**good, **bad})
    with pytest.raises(ValidationError):
        NodeConfig.model_validate({k: v for k, v in good.items() if k != "effort"})
    with pytest.raises(ValidationError, match="400"):
        NodeConfig.model_validate({**good, "output_schema": "sgw.agent.x.Model"})
    with pytest.raises(ValidationError):
        NodeConfig.model_validate({**good, "model": "claude-sonnet-5-5"})


def _row(**kw: object) -> dict:
    base = {
        "metric": "coverage_80",
        "value": 0.82,
        "unit": "share",
        "n": 120,
        "split": "heldout_family_b",
        "label": "C",
        "baseline_name": "wind threshold",
        "baseline_value": 0.61,
        "threshold": 0.75,
        "direction": "higher_is_better",
        "passed": True,
    }
    return {**base, **kw}


def test_eval_report_rows() -> None:
    EvalReport.model_validate(
        {
            "name": "release",
            "created_at": "2026-11-22T00:00:00Z",
            "code_version": "abc",
            "llm_mode": "replay",
            "command": "make eval MODE=replay",
            "metrics": [_row()],
        }
    )
    with pytest.raises(ValidationError, match="disagrees"):
        MetricRow.model_validate(_row(passed=False))
    with pytest.raises(ValidationError):
        MetricRow.model_validate(_row(value=float("nan")))
    with pytest.raises(ValidationError):
        MetricRow.model_validate(_row(split="test"))


def test_span_carries_k12_fields() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("sgw")
    attrs = telemetry.span_attributes(
        run_id="run_1",
        classification=Classification.C2,
        user_role="command",
        run_mode=RunMode.REPLAY,
        ledger_seq=42,
        node="narrate",
    )
    with tracer.start_as_current_span("node.narrate", attributes=attrs):
        pass
    (span,) = exporter.get_finished_spans()
    assert telemetry.missing_required(span.attributes) == []
    assert span.attributes["sgw.ledger_seq"] == 42
    with pytest.raises(ValueError):
        telemetry.span_attributes(
            run_id=None, classification=Classification.C1, user_role="x", run_mode=RunMode.REPLAY, made_up="y"
        )
    assert telemetry.missing_required({"sgw.run_id": "r"}) == [
        "sgw.classification",
        "sgw.user_role",
        "sgw.run_mode",
    ]
    assert isinstance(trace.get_tracer_provider(), object)


def test_ppm_helpers() -> None:
    from sgw.contracts.base import ppm_from_fraction
    from sgw.contracts.vocab import RiskBand, high_water, risk_band_for

    assert ppm_from_fraction(0.123456) == 123456
    with pytest.raises(ValueError):
        ppm_from_fraction(float("nan"))
    assert risk_band_for(0) is RiskBand.VERY_LOW and risk_band_for(1_000_000) is RiskBand.VERY_HIGH
    assert risk_band_for(799_999) is RiskBand.HIGH
    assert high_water(Classification.C1, Classification.C3, Classification.C0) is Classification.C3
    assert datetime(2024, 1, 1, tzinfo=UTC)
