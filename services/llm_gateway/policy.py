from __future__ import annotations

import fnmatch
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .prices import PRICES_PER_MTOK

SAMPLING_PARAMS = ("temperature", "top_p", "top_k")
FORCED_TOOL_CHOICE = frozenset({"any", "tool"})
ALLOWED_THINKING_TYPES = frozenset({"adaptive"})
EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})
ALLOWED_TOP_LEVEL = frozenset(
    {
        "model",
        "max_tokens",
        "messages",
        "system",
        "tools",
        "tool_choice",
        "thinking",
        "output_config",
        "stream",
        "metadata",
        "stop_sequences",
        "cache_control",
    }
)
CUSTOM_TOOL_TYPES = frozenset({None, "custom"})
MODEL_ALIASES = {
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
    "opus": "claude-opus-5-5",
}


@dataclass(frozen=True)
class NodeRule:
    models: tuple[str, ...]
    class_ceiling: str = "C1"
    betas: frozenset[str] = frozenset()
    tool_types: frozenset[str] = frozenset()
    source_types: frozenset[str] = frozenset()
    routes: frozenset[str] = frozenset({"R1"})


DEFAULT_RULES: dict[str, NodeRule] = {
    "spike.*": NodeRule(("claude-sonnet-5-5", "claude-haiku-5-5"), class_ceiling="C2"),
    "test.*": NodeRule(("claude-sonnet-5-5", "claude-haiku-5-5"), class_ceiling="C2"),
}


@dataclass
class PolicyViolation(Exception):
    code: str
    message: str
    status: int = 400

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class NodeAllowlist:
    def __init__(self, rules: Mapping[str, NodeRule | tuple[str, ...]]) -> None:
        self.rules = {k: (v if isinstance(v, NodeRule) else NodeRule(tuple(v))) for k, v in rules.items()}

    @classmethod
    def load(cls, path: Path | None) -> NodeAllowlist:
        if path is None or not path.is_file():
            return cls(DEFAULT_RULES)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        nodes = raw.get("nodes", raw)
        if isinstance(nodes, list):
            nodes = {str(n.get("node")): n for n in nodes if isinstance(n, Mapping) and n.get("node")}
        rules: dict[str, NodeRule] = {}
        for name, cfg in nodes.items():
            if not isinstance(cfg, Mapping):
                continue
            models = list(cfg.get("models") or ([cfg["model"]] if cfg.get("model") else []))
            models = [MODEL_ALIASES.get(str(m), str(m)) for m in models]
            if cfg.get("fallback_model"):
                models.append(MODEL_ALIASES.get(str(cfg["fallback_model"]), str(cfg["fallback_model"])))
            rules[str(name)] = NodeRule(
                models=tuple(str(m) for m in models),
                class_ceiling=str(cfg.get("class_ceiling", "C1")).upper(),
                betas=frozenset(str(b) for b in cfg.get("betas") or ()),
                tool_types=frozenset(str(t) for t in cfg.get("tool_types") or ()),
                source_types=frozenset(str(t) for t in cfg.get("source_types") or ()),
                routes=frozenset(str(r) for r in cfg.get("routes") or ("R1",)),
            )
        return cls({**DEFAULT_RULES, **rules})

    def rule_for(self, node: str) -> NodeRule | None:
        if node in self.rules:
            return self.rules[node]
        for pattern, rule in self.rules.items():
            if fnmatch.fnmatchcase(node, pattern):
                return rule
        return None

    def models_for(self, node: str) -> tuple[str, ...]:
        rule = self.rule_for(node)
        return rule.models if rule else ()


def _blocks(body: Mapping[str, Any]) -> Iterator[tuple[str, dict[str, Any], dict[str, Any] | None]]:
    for message in body.get("messages") or []:
        role = message.get("role", "")
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            yield role, block, None
            if block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                for inner in block["content"]:
                    if isinstance(inner, dict):
                        yield role, inner, block


INLINE_SOURCES = frozenset({"text", "content"})
SOURCE_BLOCKS = frozenset({"document", "image"})


def content_sources(body: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Every document or image source in the messages (tool results and `content` sources included), as
    (`<block>.<source type>`, source)."""
    stack: list[Any] = [block for _, block, _ in _blocks(body)]
    while stack:
        block = stack.pop()
        if not isinstance(block, Mapping) or block.get("type") not in SOURCE_BLOCKS:
            continue
        source = block.get("source")
        if not isinstance(source, Mapping):
            yield f"{block.get('type')}.invalid", {}
            continue
        yield f"{block.get('type')}.{source.get('type')}", source
        if source.get("type") == "content" and isinstance(source.get("content"), list):
            stack.extend(source["content"])


def _citations_on(block: Mapping[str, Any]) -> bool | None:
    cit = block.get("citations")
    if isinstance(cit, Mapping):
        return bool(cit.get("enabled"))
    return None


def check_payload(body: Mapping[str, Any]) -> None:
    for param in SAMPLING_PARAMS:
        if param in body:
            raise PolicyViolation("sgw_sampling_param", f"{param} is never set (K14, VT-11)")
    if "fallbacks" in body:
        raise PolicyViolation("sgw_fallbacks_off", "server-side refusal fallbacks are off (DC-14)")
    if extra := sorted(set(body) - ALLOWED_TOP_LEVEL):
        raise PolicyViolation("sgw_param_not_allowed", f"request fields {extra} are not allowed")
    model = body.get("model")
    if not isinstance(model, str) or model not in PRICES_PER_MTOK:
        raise PolicyViolation("sgw_unknown_model", f"model {model!r} has no price row; refusing unknown cost")
    max_tokens = body.get("max_tokens")
    if not isinstance(max_tokens, int) or max_tokens <= 0:
        raise PolicyViolation("sgw_max_tokens", "max_tokens must be an explicit positive integer")
    choice = body.get("tool_choice")
    if isinstance(choice, Mapping) and choice.get("type") in FORCED_TOOL_CHOICE:
        raise PolicyViolation("sgw_forced_tool_choice", "forced tool_choice returns 400 on 5.5 models")
    thinking = body.get("thinking")
    if thinking is not None and (
        not isinstance(thinking, Mapping) or thinking.get("type") not in ALLOWED_THINKING_TYPES
    ):
        raise PolicyViolation("sgw_thinking", "thinking must be omitted or adaptive (DC-14)")
    output_config = body.get("output_config") or {}
    if output_config.get("effort") not in EFFORT_LEVELS:
        raise PolicyViolation("sgw_effort_implicit", "output_config.effort must be set explicitly (K14)")

    structured = "format" in output_config
    search_settings: set[bool] = set()
    for role, block, _parent in _blocks(body):
        btype = block.get("type")
        if btype == "tool_result" and isinstance(block.get("content"), list):
            inner_types = {b.get("type") for b in block["content"] if isinstance(b, dict)}
            if "search_result" in inner_types and inner_types != {"search_result"}:
                raise PolicyViolation(
                    "sgw_mixed_search_result", "a tool_result with search_result may hold only search_result"
                )
        if btype == "search_result":
            search_settings.add(bool(_citations_on(block)))
        citations_enabled = btype in {"search_result", "document"} and _citations_on(block)
        cited_text = btype == "text" and bool(block.get("citations"))
        if cited_text and role == "user":
            raise PolicyViolation("sgw_user_citations", "text with citations may not be sent as user input")
        if structured and (citations_enabled or cited_text):
            raise PolicyViolation(
                "sgw_citations_with_format",
                "citations and output_config.format in one request return 400; use a fresh message list",
            )
    if len(search_settings) > 1:
        raise PolicyViolation("sgw_mixed_citation_settings", "all search_result blocks must share citations")
