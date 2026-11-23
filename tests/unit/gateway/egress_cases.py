"""One case table for the egress policy: the Python reference and the Rego under OPA must agree on all."""

from __future__ import annotations

from typing import Any

RULE = {
    "models": ["claude-sonnet-5-5"],
    "class_ceiling": "C1",
    "betas": ["context-1m"],
    "tool_types": ["web_search_20260209"],
    "source_types": ["image.base64"],
}
BASE: dict[str, Any] = {
    "route": "R1",
    "node": "narrate_brief",
    "model": "claude-sonnet-5-5",
    "classes": ["C0", "C1"],
    "pseudonymized": False,
    "betas": [],
    "tool_types": [],
    "source_types": [],
    "detectors": {"canary_hits": 0, "secret_hits": 0},
    "node_rule": RULE,
}


def case(**changes: Any) -> dict[str, Any]:
    out = {**BASE, **changes}
    return {k: v for k, v in out.items() if v is not ...}


C2_RULE = {**RULE, "class_ceiling": "C2"}
C4_RULE = {**RULE, "class_ceiling": "CX"}

CASES: list[tuple[str, dict[str, Any], tuple[str, ...]]] = [
    ("base", case(), ()),
    ("c0_only", case(classes=["C0"]), ()),
    ("c2_on_r1", case(classes=["C2"], node_rule=C2_RULE), ("class_not_allowed_on_route",)),
    (
        "c2_on_r2_plain",
        case(route="R2", classes=["C2"], node_rule=C2_RULE),
        ("class_requires_pseudonymization",),
    ),
    ("c2_on_r2_pseudo", case(route="R2", classes=["C2"], node_rule=C2_RULE, pseudonymized=True), ()),
    (
        "c2_on_r2_flag_missing",
        case(route="R2", classes=["C2"], node_rule=C2_RULE, pseudonymized=...),
        ("class_requires_pseudonymization",),
    ),
    ("c3_r1", case(classes=["C1", "C3"], node_rule=C4_RULE), ("class_not_allowed_on_route",)),
    ("c3_r2", case(route="R2", classes=["C3"], node_rule=C4_RULE), ("class_not_allowed_on_route",)),
    ("c3n_r1", case(classes=["C3-N"], node_rule=C4_RULE), ("class_not_allowed_on_route",)),
    ("c4_r2", case(route="R2", classes=["C4"], node_rule=C4_RULE), ("class_not_allowed_on_route",)),
    ("cx_r1", case(classes=["CX"], node_rule=C4_RULE), ("class_not_allowed_on_route",)),
    ("c3_under_c1_ceiling", case(classes=["C3"]), ("class_above_node_ceiling", "class_not_allowed_on_route")),
    ("no_classes", case(classes=[]), ("unclassified_payload",)),
    ("classes_not_list", case(classes="C1"), ("unclassified_payload",)),
    ("classes_missing", case(classes=...), ("unclassified_payload",)),
    ("unknown_label", case(classes=["C9"]), ("unknown_class_label",)),
    ("route_r3", case(route="R3"), ("route_unknown",)),
    ("route_missing", case(route=...), ("route_unknown",)),
    ("canary", case(detectors={"canary_hits": 1, "secret_hits": 0}), ("canary_detected",)),
    ("secret", case(detectors={"canary_hits": 0, "secret_hits": 1}), ("secret_detected",)),
    ("detectors_missing", case(detectors=...), ("detectors_missing",)),
    ("detector_partial", case(detectors={"canary_hits": 0}), ("detectors_missing",)),
    ("no_rule", case(node_rule=None), ("node_not_configured",)),
    ("rule_missing", case(node_rule=...), ("node_not_configured",)),
    ("rule_empty", case(node_rule={}), ("node_ceiling_invalid", "node_not_configured")),
    ("rule_no_models", case(node_rule={**RULE, "models": []}), ("node_not_configured",)),
    ("model_not_allowed", case(model="claude-opus-5-5"), ("model_not_allowed",)),
    ("model_missing", case(model=...), ("model_not_allowed",)),
    ("ceiling_invalid", case(node_rule={**RULE, "class_ceiling": "C7"}), ("node_ceiling_invalid",)),
    ("above_ceiling", case(node_rule={**RULE, "class_ceiling": "C0"}), ("class_above_node_ceiling",)),
    ("beta_ok", case(betas=["context-1m"]), ()),
    ("beta_denied", case(betas=["mcp-client-2025-11-20"]), ("beta_not_allowed",)),
    ("tool_ok", case(tool_types=["web_search_20260209"]), ()),
    ("tool_denied", case(tool_types=["code_execution_20260521"]), ("tool_type_not_allowed",)),
    ("source_ok", case(source_types=["image.base64"]), ()),
    ("source_b64_doc_denied", case(source_types=["document.base64"]), ("source_type_not_allowed",)),
    ("source_url_denied", case(source_types=["document.url", "image.base64"]), ("source_type_not_allowed",)),
    (
        "rule_without_lists",
        case(
            node_rule={"models": ["claude-sonnet-5-5"], "class_ceiling": "C1"},
            betas=["b"],
            tool_types=["t"],
            source_types=["document.file"],
        ),
        ("beta_not_allowed", "source_type_not_allowed", "tool_type_not_allowed"),
    ),
    (
        "many_reasons",
        case(classes=["C4"], detectors={"canary_hits": 2, "secret_hits": 1}, model="x", betas=["b"]),
        (
            "beta_not_allowed",
            "canary_detected",
            "class_above_node_ceiling",
            "class_not_allowed_on_route",
            "model_not_allowed",
            "secret_detected",
        ),
    ),
]
