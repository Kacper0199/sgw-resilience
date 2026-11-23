"""Run context shared by the assets of one pipeline run."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sgw.contracts.adapter import Adapter
from sgw.contracts.vocab import FeedMode, RunMode

PACKAGE = "sgw-resilience-platform"


def code_version() -> str:
    try:
        return importlib.metadata.version(PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


@dataclass
class RunContext:
    namespace: str
    run_mode: RunMode
    feed_mode: FeedMode
    now: datetime
    adapters: list[Adapter]
    as_of: datetime | None = None
    from_start: bool = False
    env: Mapping[str, str] = field(default_factory=dict)
    code_version: str = field(default_factory=code_version)
    state: dict[str, Any] = field(default_factory=dict)
