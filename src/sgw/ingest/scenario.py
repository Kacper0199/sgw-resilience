"""Scenario loading by name: every K9 file under `data/fixtures/<scenario>/*.jsonl`, merged and grouped by
source. `helene_micro` (one `all.jsonl`) and the generated `helene` (one file per feed) load the same way."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sgw.contracts.events import SOURCE_EVENTS, EnvelopeBase
from sgw.contracts.fixtures import FixtureHeader, read_fixture

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "data" / "fixtures"
SCENARIO_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RESERVED = frozenset({"llm", "eventlog"})


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Scenario:
    name: str
    headers: tuple[FixtureHeader, ...]
    events: tuple[EnvelopeBase, ...]

    @property
    def window_start(self) -> datetime:
        return min(h.scenario_window.start_utc for h in self.headers)

    @property
    def window_end(self) -> datetime:
        return max(h.scenario_window.end_utc for h in self.headers)

    @property
    def body_sha256(self) -> tuple[str, ...]:
        return tuple(h.body_sha256 for h in self.headers)

    def source_events(self) -> list[EnvelopeBase]:
        return [e for e in self.events if e.type in SOURCE_EVENTS]

    def platform_events(self) -> list[EnvelopeBase]:
        return [e for e in self.events if e.type not in SOURCE_EVENTS]

    def by_source(self, *, include_platform: bool = False) -> dict[str, list[EnvelopeBase]]:
        chosen = self.events if include_platform else tuple(self.source_events())
        grouped: dict[str, list[EnvelopeBase]] = {}
        for event in chosen:
            grouped.setdefault(event.source_id, []).append(event)
        return dict(sorted(grouped.items()))


def scenario_dir(name: str, root: Path | None = None) -> Path:
    if not SCENARIO_NAME.match(name) or name in RESERVED:
        raise ScenarioError(f"invalid scenario name {name!r}")
    return (root or FIXTURES_ROOT) / name


def available_scenarios(root: Path | None = None) -> list[str]:
    base = root or FIXTURES_ROOT
    if not base.is_dir():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir() and p.name not in RESERVED and SCENARIO_NAME.match(p.name) and any(p.glob("*.jsonl"))
    )


def load_scenario(name: str, root: Path | None = None) -> Scenario:
    folder = scenario_dir(name, root)
    files = sorted(folder.glob("*.jsonl"))
    if not files:
        known = ", ".join(available_scenarios(root)) or "none"
        raise ScenarioError(f"no fixture files for scenario {name!r} in {folder} (available: {known})")
    headers: list[FixtureHeader] = []
    events: list[EnvelopeBase] = []
    for path in files:
        header, body = read_fixture(path)
        headers.append(header)
        events.extend(body)
    keys = [e.dedup_key for e in events]
    if len(keys) != len(set(keys)):
        raise ScenarioError(f"scenario {name!r}: a dedup_key appears in more than one feed file")
    events.sort(key=lambda e: (e.event_time, e.dedup_key))
    return Scenario(name=name, headers=tuple(headers), events=tuple(events))
