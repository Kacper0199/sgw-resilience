"""Water telemetry from a K9 SCADA fixture: per-device time series (`scada-water` DeviceState events)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from sgw.generator.config import FIXTURES_DIR


def epoch(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


@dataclass(frozen=True)
class Series:
    device_id: str
    asset_id: str
    tag: str
    unit: str | None
    t: np.ndarray
    known_t: np.ndarray
    value: np.ndarray

    def at_or_before(self, when: float, known: bool = True) -> float | None:
        ref = self.known_t if known else self.t
        idx = np.flatnonzero(ref <= when)
        return None if not len(idx) else float(self.value[idx[-1]])


def load_water_series(fixture: str | Path = "helene") -> dict[str, Series]:
    path = Path(fixture) if isinstance(fixture, Path) else FIXTURES_DIR / fixture / "scada.jsonl"
    rows: dict[tuple[str, str], list[tuple[float, float, Any, str, str | None]]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("source_id") != "scada-water":
                continue
            p = e["payload"]
            rows[(p["device_id"], p["tag"])].append(
                (epoch(e["event_time"]), epoch(e["known_at"]), p["value"], p["asset_id"], p.get("unit"))
            )
    out: dict[str, Series] = {}
    for (dev, tag), vals in rows.items():
        vals.sort(key=lambda r: r[0])
        numeric = all(isinstance(v[2], (int, float)) and not isinstance(v[2], bool) for v in vals)
        value = (
            np.array([float(v[2]) for v in vals]) if numeric else np.array([v[2] for v in vals], dtype=object)
        )
        out[f"{dev}:{tag}"] = Series(
            device_id=dev,
            asset_id=vals[0][3],
            tag=tag,
            unit=vals[0][4],
            t=np.array([v[0] for v in vals]),
            known_t=np.array([v[1] for v in vals]),
            value=value,
        )
    return out
