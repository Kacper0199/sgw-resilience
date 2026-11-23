from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .canonical import CANONICAL_VERSION
from .prices import PRICE_TABLE_VERSION
from .redact import assert_no_key

RECORDING_FORMAT = "sgw.llm_recording/v1"
_NODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ReplayMiss(LookupError):
    def __init__(self, node: str, request_sha256: str) -> None:
        super().__init__(f"no recording for node={node} request_sha256={request_sha256}")
        self.node = node
        self.request_sha256 = request_sha256


def validate_node(node: str) -> str:
    if not _NODE_RE.match(node):
        raise ValueError(f"invalid x-sgw-node {node!r}: lowercase [a-z0-9_.-], at most 64 chars")
    return node


@dataclass(frozen=True)
class Recording:
    node: str
    request_sha256: str
    prompt_version: str | None
    model: str
    data_classes: list[str]
    request: dict[str, Any] | None
    request_headers: dict[str, Any]
    response: dict[str, Any]
    cost_usd_at_record: float
    latency_ms: int
    recorded_at: str

    def to_json(self) -> dict[str, Any]:
        return {
            "format": RECORDING_FORMAT,
            "canonical_version": CANONICAL_VERSION,
            "price_table": PRICE_TABLE_VERSION,
            "node": self.node,
            "request_sha256": self.request_sha256,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "data_classes": self.data_classes,
            "request_redacted": self.request is None,
            "request": self.request,
            "request_headers": self.request_headers,
            "response": self.response,
            "cost_usd_at_record": self.cost_usd_at_record,
            "latency_ms": self.latency_ms,
            "recorded_at": self.recorded_at,
        }


class RecordingStore:
    def __init__(self, root: Path, *, secrets: tuple[str | None, ...] = ()) -> None:
        self.root = root
        self._secrets = secrets

    def path_for(self, node: str, request_sha256: str) -> Path:
        validate_node(node)
        if not _HASH_RE.match(request_sha256):
            raise ValueError("request_sha256 must be 64 lowercase hex chars")
        return self.root / node / f"{request_sha256}.json"

    def exists(self, node: str, request_sha256: str) -> bool:
        return self.path_for(node, request_sha256).is_file()

    def load(self, node: str, request_sha256: str) -> dict[str, Any]:
        path = self.path_for(node, request_sha256)
        if not path.is_file():
            raise ReplayMiss(node, request_sha256)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != RECORDING_FORMAT or data.get("request_sha256") != request_sha256:
            raise ReplayMiss(node, request_sha256)
        return data

    def save(self, rec: Recording) -> Path:
        path = self.path_for(rec.node, rec.request_sha256)
        text = json.dumps(rec.to_json(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        assert_no_key(text, *self._secrets)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".rec-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return path


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
