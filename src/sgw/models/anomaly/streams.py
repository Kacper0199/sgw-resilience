"""Per-station telemetry streams for the anomaly detectors (from a K9 SCADA fixture or the dev bench)."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from sgw.generator.config import FIXTURES_DIR
from sgw.models.water.telemetry import epoch


@dataclass
class StationStreams:
    """Readings on the station's own clock (event time, s since epoch); states as (time, value) change
    lists."""

    station: str
    pressure_id: str
    level_id: str
    p_t: np.ndarray
    p: np.ndarray
    l_t: np.ndarray
    level: np.ndarray
    pump: list[tuple[float, bool]]
    breaker: list[tuple[float, str]]
    generator: list[tuple[float, str]]
    service_id: str | None = None
    s_t: np.ndarray | None = None
    service: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def span_days(self) -> float:
        return float((self.p_t[-1] - self.p_t[0]) / 86400.0) if len(self.p_t) > 1 else 0.0


def state_at(changes: list[tuple[float, Any]], t: float, default: Any = None) -> Any:
    value = default
    for ct, v in changes:
        if ct <= t:
            value = v
        else:
            break
    return value


def from_fixture(
    fixture: str | Path = "helene", scenario: dict[str, Any] | None = None
) -> list[StationStreams]:
    from sgw.models.water.params import scenario as load_scenario

    sc = scenario or load_scenario()
    path = Path(fixture) if isinstance(fixture, Path) else FIXTURES_DIR / fixture / "scada.jsonl"
    rows: dict[str, list[tuple[float, Any]]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            if e.get("source_id") not in ("scada-water", "scada-electric"):
                continue
            p = e["payload"]
            rows[f"{p['device_id']}:{p['tag']}"].append((epoch(e["event_time"]), p["value"]))
    for v in rows.values():
        v.sort(key=lambda r: r[0])
    hosp = sc["named"]["hospital"]
    out = []
    for st, ps in sc["named"]["pump_stations"].items():
        code = st.replace("-", "")
        pid, lid = f"PT-{code}-DISCH", f"LT-{ps['tank']}"
        p = rows[f"{pid}:discharge_pressure"]
        lv = rows[f"{lid}:level"]
        gens = [g for g in (ps.get("onsite_generator"), "MGEN-HALBERD-500" if st == "PS-17" else None) if g]
        gen_changes = sorted(x for g in gens for x in rows.get(f"{g}:state", []))
        s = StationStreams(
            station=st,
            pressure_id=pid,
            level_id=lid,
            p_t=np.array([r[0] for r in p]),
            p=np.array([float(r[1]) for r in p]),
            l_t=np.array([r[0] for r in lv]),
            level=np.array([float(r[1]) for r in lv]),
            pump=[(t, bool(v)) for t, v in rows[f"PMP-{st}-1:running"]],
            breaker=[(t, str(v)) for t, v in rows.get(f"BRK-{ps['feeder']}:state", [])],
            generator=[(t, str(v)) for t, v in gen_changes],
        )
        if hosp["zone"] == ps["zone"]:
            sv = rows[f"{hosp['pressure_sensor']}:service_pressure"]
            s.service_id = hosp["pressure_sensor"]
            s.s_t = np.array([r[0] for r in sv])
            s.service = np.array([float(r[1]) for r in sv])
        out.append(s)
    return out
