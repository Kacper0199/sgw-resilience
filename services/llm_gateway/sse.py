from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from typing import Any, Protocol

PASSTHROUGH_START_KEYS = ("type", "id", "name", "data", "tool_use_id", "content", "server_name", "caller")


def encode_event(name: str, data: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, separators=(',', ':'), ensure_ascii=False)}\n\n".encode()


class SSEAccumulator:
    """Rebuilds the final Message from a raw Messages API SSE byte stream."""

    def __init__(self) -> None:
        self._buffer = b""
        self.message: dict[str, Any] | None = None
        self._partial_json: dict[int, str] = {}
        self.error: dict[str, Any] | None = None
        self.events = 0
        self.stopped = False

    def feed(self, chunk: bytes) -> None:
        self._buffer += chunk.replace(b"\r\n", b"\n")
        while b"\n\n" in self._buffer:
            raw, self._buffer = self._buffer.split(b"\n\n", 1)
            self._handle(raw.decode("utf-8"))

    def _handle(self, raw: str) -> None:
        data_lines = [line[5:].lstrip() for line in raw.split("\n") if line.startswith("data:")]
        if not data_lines:
            return
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return
        self.events += 1
        etype = data.get("type")
        if etype == "message_start":
            self.message = copy.deepcopy(data["message"])
            self.message["content"] = []
        elif self.message is None:
            if etype == "error":
                self.error = data.get("error")
            return
        elif etype == "content_block_start":
            block = copy.deepcopy(data["content_block"])
            if block.get("type") in {"tool_use", "server_tool_use", "mcp_tool_use"}:
                self._partial_json[data["index"]] = ""
            self.message["content"].append(block)
        elif etype == "content_block_delta":
            self._apply_delta(data["index"], data["delta"])
        elif etype == "content_block_stop":
            idx = data["index"]
            if idx in self._partial_json:
                raw_json = self._partial_json.pop(idx)
                self.message["content"][idx]["input"] = json.loads(raw_json) if raw_json else {}
        elif etype == "message_delta":
            for key, value in (data.get("delta") or {}).items():
                self.message[key] = value
            usage = self.message.setdefault("usage", {})
            for key, value in (data.get("usage") or {}).items():
                if value is not None:
                    usage[key] = value
        elif etype == "message_stop":
            self.stopped = True
        elif etype == "error":
            self.error = data.get("error")

    def _apply_delta(self, idx: int, delta: dict[str, Any]) -> None:
        assert self.message is not None
        block = self.message["content"][idx]
        dtype = delta.get("type")
        if dtype == "text_delta":
            block["text"] = block.get("text", "") + delta["text"]
        elif dtype == "thinking_delta":
            block["thinking"] = block.get("thinking", "") + delta["thinking"]
        elif dtype == "signature_delta":
            block["signature"] = block.get("signature", "") + delta["signature"]
        elif dtype == "input_json_delta":
            self._partial_json[idx] = self._partial_json.get(idx, "") + delta.get("partial_json", "")
        elif dtype == "citations_delta":
            citations = block.get("citations") or []
            citations.append(delta["citation"])
            block["citations"] = citations


def synthesize_events(message: dict[str, Any]) -> Iterator[bytes]:
    """Turns a recorded final Message back into a Messages API SSE stream (replay of stream requests)."""
    start = {
        k: v
        for k, v in message.items()
        if k not in {"content", "stop_reason", "stop_sequence", "stop_details"}
    }
    start["content"] = []
    start["stop_reason"] = None
    start["stop_sequence"] = None
    usage = dict(message.get("usage") or {})
    start["usage"] = {**usage, "output_tokens": min(int(usage.get("output_tokens") or 0), 1)}
    yield encode_event("message_start", {"type": "message_start", "message": start})
    for idx, block in enumerate(message.get("content") or []):
        btype = block.get("type")
        if btype == "text":
            yield encode_event(
                "content_block_start",
                {"type": "content_block_start", "index": idx, "content_block": {"type": "text", "text": ""}},
            )
            for citation in block.get("citations") or []:
                yield _delta(idx, {"type": "citations_delta", "citation": citation})
            if block.get("text"):
                yield _delta(idx, {"type": "text_delta", "text": block["text"]})
        elif btype == "thinking":
            yield encode_event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": idx,
                    "content_block": {"type": "thinking", "thinking": "", "signature": ""},
                },
            )
            if block.get("thinking"):
                yield _delta(idx, {"type": "thinking_delta", "thinking": block["thinking"]})
            if block.get("signature"):
                yield _delta(idx, {"type": "signature_delta", "signature": block["signature"]})
        elif btype in {"tool_use", "server_tool_use", "mcp_tool_use"}:
            skeleton = {k: block[k] for k in PASSTHROUGH_START_KEYS if k in block}
            skeleton["input"] = {}
            yield encode_event(
                "content_block_start",
                {"type": "content_block_start", "index": idx, "content_block": skeleton},
            )
            yield _delta(
                idx, {"type": "input_json_delta", "partial_json": json.dumps(block.get("input") or {})}
            )
        else:
            yield encode_event(
                "content_block_start", {"type": "content_block_start", "index": idx, "content_block": block}
            )
        yield encode_event("content_block_stop", {"type": "content_block_stop", "index": idx})
    delta: dict[str, Any] = {
        "stop_reason": message.get("stop_reason"),
        "stop_sequence": message.get("stop_sequence"),
    }
    if message.get("stop_details") is not None:
        delta["stop_details"] = message["stop_details"]
    yield encode_event("message_delta", {"type": "message_delta", "delta": delta, "usage": usage})
    yield encode_event("message_stop", {"type": "message_stop"})


def _delta(idx: int, delta: dict[str, Any]) -> bytes:
    return encode_event("content_block_delta", {"type": "content_block_delta", "index": idx, "delta": delta})


class _Scanner(Protocol):
    def scan(self, text: str) -> Any: ...

    def may_end_in_canary_prefix(self, text: str) -> bool: ...


DELTA_TEXT_FIELDS = {"text_delta": "text", "thinking_delta": "thinking", "input_json_delta": "partial_json"}
SCAN_WINDOW = 256


class SSEOutputGuard:
    """Releases upstream SSE events to the client only when no canary or secret can be in them (SEC-33).

    Text, thinking and tool-input deltas are accumulated per content block; an event whose block text ends
    in what could be the start of a canary is held back until the next delta settles it. When a canary or
    secret appears, held events are dropped and `blocked_code` is set; nothing after it is released.
    """

    def __init__(self, detectors: _Scanner) -> None:
        self._detectors = detectors
        self._buffer = b""
        self._held: list[bytes] = []
        self._texts: dict[int, str] = {}
        self.blocked_code: str | None = None

    def feed(self, chunk: bytes) -> bytes:
        if self.blocked_code is not None:
            return b""
        self._buffer += chunk.replace(b"\r\n", b"\n")
        out: list[bytes] = []
        while b"\n\n" in self._buffer and self.blocked_code is None:
            raw, self._buffer = self._buffer.split(b"\n\n", 1)
            self._event(raw + b"\n\n", out)
        return b"".join(out)

    def flush(self) -> bytes:
        if self.blocked_code is not None:
            return b""
        out = b"".join(self._held) + self._buffer
        self._held.clear()
        self._buffer = b""
        return out

    def _block(self, hits: Any) -> bool:
        if hits.secret_hits:
            self.blocked_code = "sgw_key_leak_blocked"
        elif hits.canary_hits:
            self.blocked_code = "sgw_output_canary_blocked"
        else:
            return False
        self._held.clear()
        return True

    @staticmethod
    def _settles(data: dict[str, Any] | None) -> bool:
        """Held events are released by a delta that clears the prefix or by the end of a block or message;
        a `ping` or anything else in between joins the hold so the order stays intact."""
        if data is None:
            return False
        if data.get("type") in SETTLING_EVENTS:
            return True
        return data.get("type") == "content_block_delta"

    def _event(self, event: bytes, out: list[bytes]) -> None:
        text = event.decode("utf-8", errors="replace")
        if self._block(self._detectors.scan(text)):
            return
        hold = False
        data = _event_data(text)
        if data and data.get("type") == "content_block_delta":
            delta = data.get("delta") or {}
            field = DELTA_TEXT_FIELDS.get(str(delta.get("type")))
            if field and isinstance(delta.get(field), str):
                idx = int(data.get("index", 0))
                piece = delta[field]
                full = self._texts.get(idx, "") + piece
                self._texts[idx] = full[-SCAN_WINDOW:]
                window = full[-(len(piece) + SCAN_WINDOW) :]
                if self._block(self._detectors.scan(window)):
                    return
                hold = self._detectors.may_end_in_canary_prefix(window)
        if hold or (self._held and not self._settles(data)):
            self._held.append(event)
            return
        out.extend(self._held)
        self._held.clear()
        out.append(event)


SETTLING_EVENTS = frozenset({"content_block_stop", "message_delta", "message_stop", "error"})


def _event_data(raw: str) -> dict[str, Any] | None:
    lines = [line[5:].lstrip() for line in raw.split("\n") if line.startswith("data:")]
    if not lines:
        return None
    try:
        data = json.loads("\n".join(lines))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
