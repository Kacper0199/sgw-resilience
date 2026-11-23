from __future__ import annotations

import pytest
import yaml
from services.llm_gateway.policy import NodeAllowlist, PolicyViolation, check_payload

from .gateway_testkit import base_body


def _search_result(source: str, enabled: bool = True) -> dict:
    return {
        "type": "search_result",
        "source": source,
        "title": "SOP",
        "content": [{"type": "text", "text": "Lock out the feeder before patrol."}],
        "citations": {"enabled": enabled},
    }


def _tool_turn(results: list[dict]) -> list[dict]:
    return [
        {"role": "user", "content": "How do we lock out a feeder?"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "t1", "name": "search_sop", "input": {}}],
        },
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": results}]},
    ]


def _code(body: dict) -> str:
    with pytest.raises(PolicyViolation) as exc:
        check_payload(body)
    return exc.value.code


def test_baseline_payload_passes():
    check_payload(base_body())


@pytest.mark.parametrize("param", ["temperature", "top_p", "top_k"])
def test_sampling_params_rejected(param):
    assert _code(base_body(**{param: 0.2})) == "sgw_sampling_param"


@pytest.mark.parametrize("choice", ["any", "tool"])
def test_forced_tool_choice_rejected(choice):
    assert _code(base_body(tool_choice={"type": choice, "name": "x"})) == "sgw_forced_tool_choice"


def test_auto_tool_choice_allowed():
    check_payload(base_body(tool_choice={"type": "auto"}))


@pytest.mark.parametrize(
    "thinking", [{"type": "disabled"}, {"type": "enabled", "budget_tokens": 2048}, {"type": "between_tools"}]
)
def test_thinking_must_be_adaptive_or_omitted(thinking):
    assert _code(base_body(thinking=thinking)) == "sgw_thinking"


def test_effort_must_be_explicit():
    assert _code(base_body(output_config={})) == "sgw_effort_implicit"


def test_unknown_model_rejected():
    assert _code(base_body(model="claude-fable-5-2")) == "sgw_unknown_model"


def test_fallbacks_rejected():
    assert _code(base_body(fallbacks="default")) == "sgw_fallbacks_off"


def test_search_result_only_tool_results():
    check_payload(base_body(messages=_tool_turn([_search_result("sop://LK-4")])))
    mixed = [_search_result("sop://LK-4"), {"type": "text", "text": "as_of 2024-09-26"}]
    assert _code(base_body(messages=_tool_turn(mixed))) == "sgw_mixed_search_result"


def test_citations_with_output_format_rejected():
    body = base_body(
        messages=_tool_turn([_search_result("sop://LK-4")]),
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}},
    )
    assert _code(body) == "sgw_citations_with_format"


def test_replayed_cited_history_with_output_format_rejected():
    history = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "a", "citations": [{"type": "search_result_location"}]}],
        },
        {"role": "user", "content": "now as JSON"},
    ]
    body = base_body(
        messages=history,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}},
    )
    assert _code(body) == "sgw_citations_with_format"


def test_fresh_message_list_for_structured_node_passes():
    body = base_body(
        messages=[
            {"role": "user", "content": "Evidence E-101: PS-17 tripped at 14:02. Draft the rationale."}
        ],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}},
    )
    check_payload(body)


def test_user_text_with_citations_rejected():
    body = base_body(
        messages=[{"role": "user", "content": [{"type": "text", "text": "x", "citations": [{}]}]}]
    )
    assert _code(body) == "sgw_user_citations"


def test_mixed_citation_settings_rejected():
    body = base_body(messages=_tool_turn([_search_result("a"), _search_result("b", enabled=False)]))
    assert _code(body) == "sgw_mixed_citation_settings"


def test_node_allowlist_resolves_exact_names_before_patterns():
    allow = NodeAllowlist({"narrate": ("claude-sonnet-5-5",), "spike.*": ("claude-haiku-5-5",)})
    assert allow.models_for("narrate") == ("claude-sonnet-5-5",)
    assert allow.models_for("spike.extract") == ("claude-haiku-5-5",)
    assert allow.rule_for("unknown") is None


def test_k14_list_form_maps_model_aliases(tmp_path):
    path = tmp_path / "llm_nodes.yaml"
    path.write_text(
        "version: 1\nnodes:\n  - node: narrate_brief\n    model: sonnet\n    effort: low\n"
        "    max_tokens: 1024\n    prompt_version: v1\n    class_ceiling: C1\n"
    )
    rule = NodeAllowlist.load(path).rule_for("narrate_brief")
    assert rule is not None and rule.models == ("claude-sonnet-5-5",) and rule.class_ceiling == "C1"


def test_k14_contract_fields_reach_the_gate(tmp_path):
    from sgw.contracts.llm_nodes import NodeConfig, validate_nodes_yaml

    cfg = NodeConfig(
        node="answer_sop",
        model="sonnet",
        effort="medium",
        max_tokens=1024,
        prompt_version="v1",
        class_ceiling="C1",
        betas=["context-1m"],
        tool_types=["web_search_20260209"],
        source_types=["document.base64"],
    )
    data = {"version": 1, "nodes": [cfg.model_dump(mode="json")]}
    validate_nodes_yaml(data)
    path = tmp_path / "llm_nodes.yaml"
    path.write_text(yaml.safe_dump(data))
    rule = NodeAllowlist.load(path).rule_for("answer_sop")
    assert rule is not None and rule.betas == {"context-1m"}
    assert rule.tool_types == {"web_search_20260209"} and rule.source_types == {"document.base64"}


def test_allowlist_loads_k14_yaml(tmp_path):
    path = tmp_path / "llm_nodes.yaml"
    path.write_text(
        "nodes:\n  extract_note:\n    model: claude-haiku-5-5\n    fallback_model: claude-sonnet-5-5\n"
        "    effort: low\n"
    )
    allow = NodeAllowlist.load(path)
    assert allow.models_for("extract_note") == ("claude-haiku-5-5", "claude-sonnet-5-5")
