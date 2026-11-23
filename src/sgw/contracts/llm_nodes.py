"""K14 per-node LLM config schema. Values live in `src/sgw/agent/llm_nodes.yaml`. No node sets
sampling parameters; effort is always explicit."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from sgw.contracts.base import Contract
from sgw.contracts.vocab import Classification, Effort, ModelAlias


class EvalResult(Contract):
    report: str = Field(description="path under evals/reports/")
    metric: str
    value_ppm: int = Field(ge=0, le=1_000_000)
    passed: bool


Route = Literal["R1", "R2"]


def _default_routes() -> list[Route]:
    return ["R1"]


class NodeConfig(Contract):
    node: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    model: ModelAlias
    effort: Effort
    max_tokens: int = Field(ge=64, le=64_000)
    prompt_version: str = Field(pattern=r"^v\d+(\.\d+)*$")
    output_schema: str | None = Field(
        default=None, description="dotted path of a Pydantic model for structured output"
    )
    cache_breakpoints: list[str] = Field(default_factory=list)
    class_ceiling: Classification
    citations: bool = False
    betas: list[str] = Field(default_factory=list, description="anthropic-beta values the gateway allows")
    tool_types: list[str] = Field(default_factory=list, description="non-custom tool types allowed")
    source_types: list[str] = Field(
        default_factory=list,
        description="non-inline document/image sources the gateway allows, e.g. document.base64",
    )
    routes: list[Route] = Field(
        default_factory=_default_routes,
        description="egress routes the node may use; R2 is required before a pseudonymized C2 claim counts",
    )
    eval_result: EvalResult | None = None

    @model_validator(mode="after")
    def _no_citations_with_structured_output(self) -> NodeConfig:
        if self.citations and self.output_schema:
            raise ValueError("citations and structured output in one request return 400 (WP-04 trap)")
        return self


class LlmNodesFile(Contract):
    version: int = Field(ge=1)
    nodes: list[NodeConfig]

    @model_validator(mode="after")
    def _unique(self) -> LlmNodesFile:
        names = [n.node for n in self.nodes]
        if len(names) != len(set(names)):
            raise ValueError("duplicate node names")
        return self


def validate_nodes_yaml(data: dict[str, Any]) -> LlmNodesFile:
    return LlmNodesFile.model_validate(data)
