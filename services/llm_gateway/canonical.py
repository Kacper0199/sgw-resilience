from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

import rfc8785

CANONICAL_VERSION = "k11-v1"
EXCLUDED_BODY_KEYS = frozenset({"stream", "metadata"})
HASHED_HEADERS = ("anthropic-version", "anthropic-beta", "x-sgw-node", "x-sgw-prompt-version")
ID_KEYS = ("id", "tool_use_id")
ID_BLOCK_TYPES = frozenset(
    {
        "tool_use",
        "server_tool_use",
        "tool_result",
        "web_search_tool_result",
        "mcp_tool_use",
        "mcp_tool_result",
    }
)
SIGNATURE_PLACEHOLDER = "<signature>"


def _normalise_ids(body: dict[str, Any]) -> None:
    mapping: dict[str, str] = {}

    def alias(value: str) -> str:
        if value not in mapping:
            mapping[value] = f"toolu_{len(mapping):04d}"
        return mapping[value]

    for message in body.get("messages") or []:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype in ID_BLOCK_TYPES:
                for key in ID_KEYS:
                    if isinstance(block.get(key), str):
                        block[key] = alias(block[key])
            if btype == "thinking" and "signature" in block:
                block["signature"] = SIGNATURE_PLACEHOLDER
            if btype == "redacted_thinking" and "data" in block:
                block["data"] = SIGNATURE_PLACEHOLDER


def _headers_part(headers: Mapping[str, str]) -> dict[str, Any]:
    lower = {k.lower(): v for k, v in headers.items()}
    part: dict[str, Any] = {}
    for name in HASHED_HEADERS:
        value = lower.get(name)
        if value is None:
            continue
        if name == "anthropic-beta":
            part[name] = sorted({b.strip() for b in value.split(",") if b.strip()})
        else:
            part[name] = value.strip()
    return part


def canonical_request(body: Mapping[str, Any], headers: Mapping[str, str]) -> dict[str, Any]:
    cleaned = {k: copy.deepcopy(v) for k, v in body.items() if k not in EXCLUDED_BODY_KEYS}
    _normalise_ids(cleaned)
    return {"canonical_version": CANONICAL_VERSION, "body": cleaned, "headers": _headers_part(headers)}


def canonical_bytes(body: Mapping[str, Any], headers: Mapping[str, str]) -> bytes:
    return rfc8785.dumps(canonical_request(body, headers))


def request_hash(body: Mapping[str, Any], headers: Mapping[str, str]) -> str:
    return hashlib.sha256(canonical_bytes(body, headers)).hexdigest()
