from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
CANARY_PATTERN = re.compile(r"CANARY-[0-9A-F]{4,}", re.IGNORECASE)
SECRET_HEADER_NAMES = frozenset({"x-api-key", "authorization", "proxy-authorization", "cookie"})
CONTENT_FIELDS = frozenset(
    {"messages", "system", "tools", "content", "text", "thinking", "input", "partial_json"}
)
CLASS_ORDER = ("C0", "C1", "C2", "C3", "C3-N", "C4", "CX")
VERBATIM_MAX_CLASS = "C1"
DENY_FROM_CLASS = "C3"


class KeyLeakError(RuntimeError):
    pass


def class_rank(label: str) -> int:
    label = label.strip().upper()
    if label not in CLASS_ORDER:
        return CLASS_ORDER.index("CX")
    return CLASS_ORDER.index(label)


class MissingClassesError(ValueError):
    pass


def parse_classes(header: str | None) -> list[str]:
    labels = [p.strip().upper() for p in (header or "").split(",") if p.strip()]
    if not labels:
        raise MissingClassesError("x-sgw-classes is required (e.g. C0 or C1,C2)")
    return sorted(set(labels), key=class_rank)


def max_class(labels: Iterable[str]) -> str:
    return max(labels, key=class_rank, default="C1")


def is_denied(labels: Iterable[str]) -> bool:
    return class_rank(max_class(labels)) >= class_rank(DENY_FROM_CLASS)


def may_store_verbatim(labels: Iterable[str]) -> bool:
    return class_rank(max_class(labels)) <= class_rank(VERBATIM_MAX_CLASS)


def scrub_text(text: str) -> str:
    return CANARY_PATTERN.sub("<redacted-canary>", KEY_PATTERN.sub("<redacted-key>", text))


def assert_no_key(serialised: str, *secrets: str | None) -> None:
    if KEY_PATTERN.search(serialised):
        raise KeyLeakError("an Anthropic key-shaped token was about to be persisted")
    for secret in secrets:
        if secret and secret in serialised:
            raise KeyLeakError("the gateway key was about to be persisted")


def safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        k: ("<redacted>" if k.lower() in SECRET_HEADER_NAMES else scrub_text(v)) for k, v in headers.items()
    }


def redact_for_log(event: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in event.items():
        if key in CONTENT_FIELDS:
            out[key] = "<omitted>"
        elif isinstance(value, Mapping):
            out[key] = redact_for_log(value)
        elif isinstance(value, str):
            out[key] = scrub_text(value)
        else:
            out[key] = value
    return out
