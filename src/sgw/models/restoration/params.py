"""Labelled parameters of the restoration process and ETR model (`params.yaml`); the crew duty clock."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

PARAMS_PATH = Path(__file__).with_name("params.yaml")
LABELS = frozenset({"F", "C", "A", "P"})
DAY_S = 86400.0


@dataclass(frozen=True)
class Param:
    key: str
    value: Any
    unit: str
    label: str
    source: str


@dataclass(frozen=True)
class Params:
    groups: dict[str, dict[str, Param]]

    def p(self, group: str, key: str) -> Param:
        return self.groups[group][key]

    def f(self, group: str, key: str) -> float:
        return float(self.p(group, key).value)

    def arr(self, group: str, key: str) -> np.ndarray:
        return np.asarray(self.p(group, key).value, dtype=float)

    def seeds(self, split: str) -> list[int]:
        lo, hi = self.p("splits", f"{split}_seeds").value
        return list(range(int(lo), int(hi)))

    def with_values(self, group: str, **values: Any) -> Params:
        groups = {g: dict(v) for g, v in self.groups.items()}
        for key, value in values.items():
            old = groups[group][key]
            groups[group][key] = Param(key, value, old.unit, old.label, old.source)
        return Params(groups)


def load_params(path: Path = PARAMS_PATH) -> Params:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    groups: dict[str, dict[str, Param]] = {}
    for group, entries in raw.items():
        groups[group] = {}
        for key, e in entries.items():
            if e["label"] not in LABELS:
                raise ValueError(f"{group}.{key}: label {e['label']!r} not in {sorted(LABELS)}")
            groups[group][key] = Param(key, e["value"], e["unit"], e["label"], e["source"])
    return Params(groups)


@cache
def default_params() -> Params:
    return load_params()


@dataclass(frozen=True)
class DutyClock:
    """Crews work `on_h` h a day from `start_utc_h`; maps wall time (epoch s) to cumulative on-duty hours."""

    on_h: float
    start_utc_h: float

    @classmethod
    def from_params(cls, prm: Params) -> DutyClock:
        return cls(prm.f("process", "shift_on_h"), prm.f("process", "shift_start_utc_h"))

    def hours(self, t: Any) -> Any:
        x = np.asarray(t, dtype=float) - self.start_utc_h * 3600.0
        d = np.floor(x / DAY_S)
        r = np.clip((x - d * DAY_S) / 3600.0, 0.0, self.on_h)
        return d * self.on_h + r

    def wall(self, h: Any) -> Any:
        """Earliest wall time with `h` on-duty hours elapsed (a shift boundary maps to the shift end)."""
        h = np.asarray(h, dtype=float)
        d = np.ceil(h / self.on_h) - 1.0
        r = h - d * self.on_h
        return d * DAY_S + r * 3600.0 + self.start_utc_h * 3600.0

    def finish(self, start: Any, work_h: Any) -> Any:
        """Wall time at which `work_h` on-duty hours started at `start` are done (off-duty time skipped)."""
        return self.wall(self.hours(start) + np.asarray(work_h, dtype=float))
