"""Scoring of A7/A8 alarms against truth windows (dev split only).

A fault counts as detected when an alarm of the right family (A8 for sensor faults, A7 for physical ones) on
the same station raises its detection inside [fault start, fault end + grace]. An alarm episode is a false
alarm when it overlaps no truth window of its station, or when it overlaps only windows of the other family
(an A8 accusation during a real physical event, or an A7 event raised from a faulty sensor).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from sgw.models.anomaly.detect import Alarm
from sgw.models.anomaly.devbench import PHYSICAL_FAULTS, SENSOR_FAULTS, TruthWindow
from sgw.models.water.params import ARTEFACT_DIR, scenario
from sgw.models.water.telemetry import epoch

GRACE_S = 2 * 3600.0
SPOOF_KINDS = {"replay_pressure", "replay_level"}
HELENE_FAULT_KINDS = {
    "PUMP-TRIP": "pump_trip",
    "REPLAY-SPOOF": "replay_pressure",
    "STUCK-LEVEL": "stuck_level",
    "DRIFT": "drift_pressure",
    "LEAK": "leak",
}


PAIR = {"pressure_level_inconsistent", "service_pressure_inconsistent"}
ACCEPTED_KINDS = {
    "pump_trip": {"pump_trip", "pressure_loss"},
    "leak": {"demand_increase"},
    "stuck_level": {"frozen_reading", "pressure_level_inconsistent"},
    "drift_pressure": PAIR,
    "replay_pressure": PAIR | {"replayed_sequence"},
    "replay_level": {"pressure_level_inconsistent", "replayed_sequence"},
}


@dataclass
class Scored:
    faults: list[dict[str, Any]]
    false_alarms: list[dict[str, Any]]
    asset_days: float


def helene_truth(fixture: str = "helene") -> dict[str, list[TruthWindow]]:
    table = json.loads((ARTEFACT_DIR.parents[1] / "fixtures" / fixture / "truth_table.json").read_text())
    end = epoch(scenario()["telemetry_window"]["end_utc"])
    out: dict[str, list[TruthWindow]] = {}
    for case in table["seeded_cases"]:
        if case["kind"] != "water_fault":
            continue
        station = "PS-" + case["id"].split("-")[1][2:]
        kind = next(v for k, v in HELENE_FAULT_KINDS.items() if case["id"].endswith(k))
        start = epoch(case["pin"]["from_utc"])
        dur = case["pin"].get("duration_h")
        fam = "A8" if kind in SENSOR_FAULTS else "A7"
        out.setdefault(station, []).append(
            TruthWindow(
                kind,
                fam,
                start,
                end if dur is None else start + float(dur) * 3600.0,
                detail={"id": case["id"]},
            )
        )
    for station, w in table["water"].items():
        if not station.startswith("PS-") or w["grid_loss_utc"] is None:
            continue
        back = w["back_above_floor_utc"] or w["grid_restore_utc"]
        out.setdefault(station, []).append(
            TruthWindow(
                "low_pressure_episode",
                "A7",
                epoch(w["grid_loss_utc"]),
                (epoch(back) if back else end) + GRACE_S,
            )
        )
    return out


def _overlaps(a: Alarm, w: TruthWindow) -> bool:
    return a.start <= w.end + GRACE_S and a.end >= w.start


def score(alarms: dict[str, list[Alarm]], truth: dict[str, list[TruthWindow]], asset_days: float) -> Scored:
    faults = []
    false_alarms = []
    for station, windows in truth.items():
        mine = alarms.get(station, [])
        for w in windows:
            if w.kind not in SENSOR_FAULTS + PHYSICAL_FAULTS:
                continue
            hits = [
                a
                for a in mine
                if a.family == w.family
                and w.start <= a.detected <= w.end + GRACE_S
                and a.kind in ACCEPTED_KINDS[w.kind]
                and (w.device is None or w.device in a.devices)
            ]
            first = min(hits, key=lambda a: a.detected) if hits else None
            faults.append(
                {
                    "station": station,
                    "kind": w.kind,
                    "family": w.family,
                    "id": w.detail.get("id"),
                    "detected": first is not None,
                    "by": None if first is None else first.kind,
                    "delay_min": None if first is None else round((first.detected - w.start) / 60.0, 1),
                    "observable": bool(w.detail.get("observable", True)),
                    "consequential": bool(w.detail.get("consequential", True)),
                }
            )
    for station, mine in alarms.items():
        windows = truth.get(station, [])
        for a in mine:
            same = [w for w in windows if _overlaps(a, w) and w.family == a.family]
            other = [w for w in windows if _overlaps(a, w) and w.family != a.family]
            physical_ok = a.family == "A7" and any(w.kind == "low_pressure_episode" for w in other)
            if not same and not physical_ok:
                false_alarms.append(
                    {
                        "station": station,
                        "family": a.family,
                        "kind": a.kind,
                        "reason": "other_family_only" if other else "no_truth_window",
                        "start": a.start,
                        "end": a.end,
                    }
                )
    return Scored(faults, false_alarms, asset_days)


def metrics(s: Scored) -> dict[str, Any]:
    n = len(s.faults)
    det = sum(f["detected"] for f in s.faults)
    spoof = [f for f in s.faults if f["kind"] in SPOOF_KINDS]
    delays = [f["delay_min"] for f in s.faults if f["delay_min"] is not None]
    by_kind: dict[str, dict[str, int]] = {}
    for f in s.faults:
        k = by_kind.setdefault(f["kind"], {"n": 0, "detected": 0})
        k["n"] += 1
        k["detected"] += int(f["detected"])
    fa = len(s.false_alarms)
    seen = [f for f in s.faults if f["observable"] and f["consequential"]]
    cons = [f for f in spoof if f["consequential"]]
    return {
        "faults": n,
        "detected": det,
        "recall": det / n if n else float("nan"),
        "recall_wilson95": _wilson(det, n),
        "by_kind": by_kind,
        "false_alarms": fa,
        "false_alarms_a7": sum(1 for f in s.false_alarms if f["family"] == "A7"),
        "false_alarms_a8": sum(1 for f in s.false_alarms if f["family"] == "A8"),
        "asset_days": s.asset_days,
        "fa_per_100_asset_days": 100.0 * fa / s.asset_days if s.asset_days else float("nan"),
        "spoof_cases": len(spoof),
        "spoof_flagged": sum(f["detected"] for f in spoof),
        "physically_detectable_faults": len(seen),
        "recall_physically_detectable": sum(f["detected"] for f in seen) / len(seen)
        if seen
        else float("nan"),
        "recall_physically_detectable_wilson95": _wilson(sum(f["detected"] for f in seen), len(seen)),
        "spoof_consequential": len(cons),
        "spoof_consequential_flagged": sum(f["detected"] for f in cons),
        "median_delay_min": float(np.median(delays)) if delays else None,
    }


def _wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(float(c - h), 4), round(float(c + h), 4)]
