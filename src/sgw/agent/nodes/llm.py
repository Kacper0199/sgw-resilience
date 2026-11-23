"""LLM access for agent nodes: only through the gateway (K13), configured per node from K14.

The client is the Anthropic SDK with `base_url` at the gateway, the service's caller token (M4) as the key
and `max_retries=0` (the gateway owns retries, budget, egress and replay). Every request carries the K13
tags, with `x-sgw-classes` taken from the evidence view that built the prompt, never from a
constant. Failures that a node must survive (gateway down, replay miss, egress or budget denial, breaker,
refusal, truncation, a missing caller token) surface as
`LlmUnavailable`, which sends the node to its M2 template.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import anthropic
import yaml

from sgw.contracts.llm_nodes import LlmNodesFile, NodeConfig
from sgw.contracts.vocab import Classification

NODES_FILE = Path(__file__).resolve().parents[1] / "llm_nodes.yaml"
MODEL_IDS: dict[str, str] = {
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
    "opus": "claude-opus-5-5",
}
DEFAULT_GATEWAY_URL = "http://127.0.0.1:8100"
PLACEHOLDER_KEY = "no-caller-token"  # noqa: S105 - sentinel the gateway refuses
TOKEN_ENV = "SGW_GATEWAY_TOKEN"  # noqa: S105 - variable name, not a secret


def caller_token() -> str | None:
    """This process's gateway token: `SGW_GATEWAY_TOKEN_<SGW_SERVICE>` (api, worker in compose), then
    `SGW_GATEWAY_TOKEN`; a host CLI run without either reads `SGW_GATEWAY_TOKEN_CLI` from the host.env that
    `sgw bootstrap` wrote. Without a token the gateway answers 401 and the node takes its M2 template."""
    service = os.environ.get("SGW_SERVICE", "").strip()
    names = ([f"{TOKEN_ENV}_{service.upper().replace('-', '_')}"] if service else []) + [TOKEN_ENV]
    for name in names:
        if value := os.environ.get(name, "").strip():
            return value
    if service:
        return None
    try:
        from sgw.cli.support import read_env_file, secrets_dir

        return read_env_file(secrets_dir() / "host.env").get(f"{TOKEN_ENV}_CLI") or None
    except Exception:  # noqa: BLE001
        return None


class LlmUnavailable(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class LlmRequest:
    node: str
    config: NodeConfig
    system: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    classes: Sequence[Classification]
    run_id: str | None = None
    output_schema: dict[str, Any] | None = None
    model_override: str | None = None

    @property
    def model_id(self) -> str:
        return MODEL_IDS[self.model_override or self.config.model.value]

    def body(self) -> dict[str, Any]:
        output: dict[str, Any] = {"effort": self.config.effort.value}
        if self.output_schema is not None:
            output["format"] = {"type": "json_schema", "schema": self.output_schema}
        return {
            "model": self.model_id,
            "max_tokens": self.config.max_tokens,
            "system": self.system,
            "messages": self.messages,
            "thinking": {"type": "adaptive"},
            "output_config": output,
        }


@dataclass(frozen=True)
class LlmResponse:
    content: list[dict[str, Any]]
    stop_reason: str | None
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None

    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") in ("tool_use", "server_tool_use")]


class LlmClient(Protocol):
    async def create(self, request: LlmRequest) -> LlmResponse: ...


@dataclass(frozen=True)
class GatewayTags:
    purpose: str = "dev"
    wave: str = "W3"
    deadline_s: int = 60

    @classmethod
    def from_env(cls) -> GatewayTags:
        return cls(
            purpose=os.environ.get("SGW_LLM_PURPOSE", "dev"),
            wave=os.environ.get("SGW_LLM_WAVE", "W3"),
            deadline_s=int(os.environ.get("SGW_LLM_DEADLINE_S", "60")),
        )


def k13_headers(request: LlmRequest, tags: GatewayTags) -> dict[str, str]:
    if not request.classes:
        raise ValueError("an LLM request needs the classes of its prompt content (D-072)")
    headers = {
        "x-sgw-node": request.node,
        "x-sgw-purpose": tags.purpose,
        "x-sgw-wave": tags.wave,
        "x-sgw-classes": ",".join(c.value for c in request.classes),
        "x-sgw-prompt-version": request.config.prompt_version,
        "x-sgw-deadline-s": str(tags.deadline_s),
    }
    if request.run_id:
        headers["x-sgw-run"] = request.run_id
    return headers


class GatewayClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        tags: GatewayTags | None = None,
        timeout_s: float = 90.0,
        http_client: Any = None,
        token: str | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("SGW_GATEWAY_URL", DEFAULT_GATEWAY_URL)
        self.tags = tags or GatewayTags.from_env()
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "api_key": token or caller_token() or PLACEHOLDER_KEY,
            "max_retries": 0,
            "timeout": timeout_s,
        }
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = anthropic.AsyncAnthropic(**kwargs)

    async def create(self, request: LlmRequest) -> LlmResponse:
        try:
            raw = await self._client.messages.with_raw_response.create(
                **request.body(), extra_headers=k13_headers(request, self.tags)
            )
            message = await raw.parse()
        except anthropic.APIConnectionError as exc:
            raise LlmUnavailable("gateway_unreachable", type(exc).__name__) from exc
        except anthropic.APIStatusError as exc:
            raise LlmUnavailable(f"gateway_{exc.status_code}", _error_type(exc)) from exc
        data = message.to_dict()
        return LlmResponse(
            content=list(data.get("content") or []),
            stop_reason=data.get("stop_reason"),
            model=str(data.get("model", request.model_id)),
            usage=dict(data.get("usage") or {}),
            call_id=raw.headers.get("x-sgw-call-id"),
        )


def _error_type(exc: anthropic.APIStatusError) -> str:
    body = exc.body
    if isinstance(body, Mapping):
        err = body.get("error")
        if isinstance(err, Mapping):
            return str(err.get("type", ""))
    return ""


@lru_cache(maxsize=4)
def load_nodes(path: Path = NODES_FILE) -> dict[str, NodeConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    parsed = LlmNodesFile.model_validate(raw)
    return {n.node: n for n in parsed.nodes}


def node_config(name: str, path: Path = NODES_FILE) -> NodeConfig:
    return load_nodes(path)[name]


def ensure_usable(response: LlmResponse) -> None:
    if response.stop_reason == "refusal":
        raise LlmUnavailable("refusal")
    if response.stop_reason == "max_tokens":
        raise LlmUnavailable("max_tokens")
