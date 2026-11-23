"""A8 spoof guard and A7 pressure anomaly detection on pump-station telemetry.

A8 (data integrity, runs first): a reading is suspect when it is physically inconsistent with its neighbours
or carries a replay or frozen signature:
- `pressure_level_inconsistent`: the discharge pressure must equal the tank head at the sensor,
  p = a + 0.433 L (the zone twin's sensor relation); two-sided CUSUM on the standardised residual;
- `service_pressure_inconsistent` (zones with a service sensor): the hospital service pressure must sit the
  twin's static offset below the station pressure;
- `frozen_reading`: a run of identical values where the sensor noise makes ties rare (not at a range end);
- `replayed_sequence`: a window of readings that repeats an earlier window exactly (noise does not repeat).
A7 (physical events, on readings A8 did not mark suspect):
- `pump_trip`: the pump stops while the station feeder is energised and no generator change explains it;
- `pressure_loss`: discharge pressure below the station low-pressure alarm, with its explanation (power loss,
  generator failure, pump trip, demand above supply);
- `demand_increase`: tank mass balance in refill or drain windows gives the zone demand; a one-sided CUSUM on
  its ratio to the station's own baseline flags a leak or main break the pressure cannot show while the tank
  is full.
Every detector is causal (uses readings up to the alarm time only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from sgw.models.anomaly.streams import StationStreams, state_at
from sgw.models.water.network import PSI_PER_FT, PathModel

PARAMS_PATH = Path(__file__).with_name("detector.yaml")
GEN_DOWN = {"failed_run", "out_of_fuel", "failed_start"}


@cache
def settings() -> dict[str, Any]:
    data = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))
    return {k: v["value"] for k, v in data["params"].items()}


@dataclass
class Alarm:
    station: str
    family: str
    kind: str
    devices: tuple[str, ...]
    start: float
    end: float
    detected: float
    detail: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0


def exceedance(peak: float, threshold: float) -> float:
    """The detector's score of one alarm: how far its test statistic went past the alarm threshold, as a
    share of the peak, (peak - threshold) / peak in [0, 1]. Detectors with no graded statistic (a status
    change, an exact replayed sequence) score 1."""
    if peak <= 0 or peak <= threshold:
        return 0.0
    return round((peak - threshold) / peak, 6)


@dataclass(frozen=True)
class SensorModel:
    sigma_p: float
    sigma_l: float
    sensor_static_psi: float
    service_offset_psi: float | None
    gal_per_ft: float
    max_level_ft: float
    pump_gpm: float
    avg_gpm: float
    hourly: np.ndarray


def sensor_model(pm: PathModel, sigma_p: float, sigma_l: float, twin: Any) -> SensorModel:
    offset = None
    if "hospital" in pm.critical_role.values():
        h = [i for i, nid in enumerate(pm.node_ids) if pm.critical_role[nid] == "hospital"][0]
        offset = float(pm.sensor_static_psi - pm.static_psi[h])
    return SensorModel(
        sigma_p=sigma_p,
        sigma_l=sigma_l,
        sensor_static_psi=pm.sensor_static_psi,
        service_offset_psi=offset,
        gal_per_ft=pm.gal_per_ft,
        max_level_ft=pm.max_level_ft,
        pump_gpm=float(twin.pump_gpm),
        avg_gpm=float(twin.avg_gpm),
        hourly=np.asarray(twin.hourly),
    )


def _episodes(flags: np.ndarray, t: np.ndarray) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    idx = np.flatnonzero(flags)
    if not len(idx):
        return out
    start = prev = int(idx[0])
    for i in idx[1:]:
        if t[i] - t[prev] > settings()["episode.merge_gap_h"] * 3600.0:
            out.append((start, prev))
            start = int(i)
        prev = int(i)
    out.append((start, prev))
    return out


def cusum_episodes(
    z: np.ndarray, k: float, h: float, two_sided: bool = True
) -> list[tuple[int, int, int, str, float]]:
    """(first index of the excursion, alarm index, last index, direction, peak statistic) per alarm; the
    statistic resets when it falls back below h/2 after an alarm."""
    out = []
    sp = sn = 0.0
    start_p = start_n = 0
    peak = 0.0
    active: tuple[int, int, str] | None = None
    for i, zi in enumerate(z):
        if np.isnan(zi):
            continue
        if sp == 0.0:
            start_p = i
        if sn == 0.0:
            start_n = i
        sp = max(0.0, sp + zi - k)
        sn = max(0.0, sn - zi - k) if two_sided else 0.0
        if active is None:
            if sp > h:
                active = (start_p, i, "up")
                peak = sp
            elif sn > h:
                active = (start_n, i, "down")
                peak = sn
        else:
            stat = sp if active[2] == "up" else sn
            peak = max(peak, stat)
            if stat < h / 2:
                out.append((active[0], active[1], i, active[2], peak))
                active = None
                sp = sn = 0.0
    if active is not None:
        out.append((active[0], active[1], len(z) - 1, active[2], peak))
    return out


def frozen_runs(x: np.ndarray, run: int, exclude_at_or_below: float | None = None) -> list[tuple[int, int]]:
    out = []
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and x[j + 1] == x[i]:
            j += 1
        if j - i + 1 >= run and not (exclude_at_or_below is not None and x[i] <= exclude_at_or_below):
            out.append((i, j))
        i = j + 1
    return out


def replay_hits(x: np.ndarray, t: np.ndarray, window: int, min_lag_s: float, max_lag_s: float) -> np.ndarray:
    seen: dict[tuple[float, ...], list[int]] = {}
    hit = np.zeros(len(x), dtype=bool)
    for i in range(window - 1, len(x)):
        chunk = x[i - window + 1 : i + 1]
        if np.all(chunk == chunk[0]):
            continue
        key = tuple(np.round(chunk, 3).tolist())
        for j in seen.get(key, []):
            if min_lag_s <= t[i] - t[j] <= max_lag_s:
                hit[i - window + 1 : i + 1] = True
                break
        seen.setdefault(key, []).append(i)
    return hit


def a8_alarms(s: StationStreams, m: SensorModel) -> list[Alarm]:
    cfg = settings()
    k, h = cfg["cusum.k_sigma"], cfg["cusum.h_sigma"]
    alarms: list[Alarm] = []
    idx = np.searchsorted(s.p_t, s.l_t)
    ok = (idx < len(s.p_t)) & (s.p_t[np.minimum(idx, len(s.p_t) - 1)] == s.l_t)
    lt = s.l_t[ok]
    p_at = s.p[idx[ok]]
    lv = s.level[ok]
    sigma_r = float(np.hypot(m.sigma_p, PSI_PER_FT * m.sigma_l))
    z = (p_at - (m.sensor_static_psi + PSI_PER_FT * lv)) / sigma_r
    z[lv <= cfg["frozen.level_range_end_ft"]] = np.nan
    for a, d, b, sign, peak in cusum_episodes(z, k, h):
        alarms.append(
            Alarm(
                s.station,
                "A8",
                "pressure_level_inconsistent",
                (s.pressure_id, s.level_id),
                float(lt[a]),
                float(lt[b]),
                float(lt[d]),
                {
                    "direction": sign,
                    "max_abs_residual_psi": round(float(np.nanmax(np.abs(z[a : b + 1]))) * sigma_r, 2),
                    "cusum_peak_sigma": round(peak, 3),
                },
                exceedance(peak, h),
            )
        )
    if s.service is not None and s.s_t is not None and m.service_offset_psi is not None:
        j = np.searchsorted(s.p_t, s.s_t)
        okj = (j < len(s.p_t)) & (s.p_t[np.minimum(j, len(s.p_t) - 1)] == s.s_t)
        st = s.s_t[okj]
        zs = (s.service[okj] - (s.p[j[okj]] - m.service_offset_psi)) / (m.sigma_p * np.sqrt(2.0))
        for a, d, b, sign, peak in cusum_episodes(zs, k, h):
            alarms.append(
                Alarm(
                    s.station,
                    "A8",
                    "service_pressure_inconsistent",
                    (s.pressure_id, s.service_id or ""),
                    float(st[a]),
                    float(st[b]),
                    float(st[d]),
                    {"direction": sign, "cusum_peak_sigma": round(peak, 3)},
                    exceedance(peak, h),
                )
            )
    for dev, t, x, run, floor in (
        (s.level_id, s.l_t, s.level, int(cfg["frozen.level_run"]), cfg["frozen.level_range_end_ft"]),
        (s.pressure_id, s.p_t, s.p, int(cfg["frozen.pressure_run"]), None),
    ):
        for a, b in frozen_runs(x, run, floor):
            alarms.append(
                Alarm(
                    s.station,
                    "A8",
                    "frozen_reading",
                    (dev,),
                    float(t[a]),
                    float(t[b]),
                    float(t[a + run - 1]),
                    {"value": float(x[a]), "readings": b - a + 1},
                    exceedance(b - a + 1, run - 1),
                )
            )
        w = int(cfg["replay.window"])
        hits = replay_hits(x, t, w, cfg["replay.min_lag_h"] * 3600.0, cfg["replay.max_lag_h"] * 3600.0)
        for a, b in _episodes(hits, t):
            alarms.append(
                Alarm(
                    s.station,
                    "A8",
                    "replayed_sequence",
                    (dev,),
                    float(t[a]),
                    float(t[b]),
                    float(t[min(a + w - 1, b)]),
                )
            )
    return alarms


def suspect_mask(t: np.ndarray, device: str, alarms: list[Alarm], own_only: bool = False) -> np.ndarray:
    """Readings of `device` from an A8 alarm's detection time to its end (causal: a reading is never marked
    suspect by an alarm raised after it). `own_only` keeps only alarms that name the device alone
    (frozen, replay), not pairwise inconsistencies, which cannot say which of the two sensors is wrong."""
    mask = np.zeros(len(t), dtype=bool)
    for a in alarms:
        if a.family == "A8" and device in a.devices and not (own_only and len(a.devices) > 1):
            mask |= (t >= a.detected) & (t <= a.end)
    return mask


def _power(s: StationStreams, t: float) -> tuple[str | None, str | None, bool | None]:
    return state_at(s.breaker, t), state_at(s.generator, t), state_at(s.pump, t)


def explain(s: StationStreams, t: float) -> str:
    breaker, gen, pump = _power(s, t)
    if gen in GEN_DOWN:
        return "generator_failure"
    if breaker == "open" and gen != "running":
        return "power_loss"
    if pump is False:
        return "pump_trip"
    return "demand_exceeds_supply"


def a7_alarms(s: StationStreams, m: SensorModel, a8: list[Alarm], alarm_psi: float) -> list[Alarm]:
    cfg = settings()
    alarms: list[Alarm] = []
    prev = None
    for i, (t, on) in enumerate(s.pump):
        if prev is True and on is False:
            breaker = state_at(s.breaker, t)
            gen_change = any(abs(gt - t) <= 120.0 for gt, _ in s.generator)
            if breaker != "open" and not gen_change:
                end = next((t2 for t2, v in s.pump[i + 1 :] if v), float(s.p_t[-1]))
                alarms.append(Alarm(s.station, "A7", "pump_trip", (f"PMP-{s.station}-1",), t, end, t))
        prev = on
    bad = suspect_mask(s.p_t, s.pressure_id, a8)
    low = (s.p < alarm_psi) & ~bad
    n = int(cfg["pressure.confirm_readings"])
    confirmed = np.zeros(len(low), dtype=bool)
    for i in range(n - 1, len(low)):
        if low[i - n + 1 : i + 1].all():
            confirmed[i - n + 1 : i + 1] = True
    for a, b in _episodes(confirmed, s.p_t):
        alarms.append(
            Alarm(
                s.station,
                "A7",
                "pressure_loss",
                (s.pressure_id,),
                float(s.p_t[a]),
                float(s.p_t[b]),
                float(s.p_t[min(a + n - 1, b)]),
                {"explanation": explain(s, float(s.p_t[a])), "min_psi": float(s.p[a : b + 1].min())},
                exceedance(alarm_psi, float(s.p[a : b + 1].min())),
            )
        )
    alarms += _demand_alarms(s, m, a8)
    return alarms


def _demand_alarms(s: StationStreams, m: SensorModel, a8: list[Alarm]) -> list[Alarm]:
    from sgw.models.water.twin import EDT_OFFSET_H

    cfg = settings()
    bad = suspect_mask(s.l_t, s.level_id, a8, own_only=True)
    lo, hi = cfg["refill.empty_margin_ft"], m.max_level_ft - cfg["refill.full_margin_ft"]
    times, ratio, sig = [], [], []
    for i in range(1, len(s.l_t)):
        t0, t1 = s.l_t[i - 1], s.l_t[i]
        if bad[i] or bad[i - 1] or not (lo < s.level[i - 1] < hi and lo < s.level[i] < hi):
            continue
        p0, p1 = state_at(s.pump, t0), state_at(s.pump, t1)
        if p0 is None or p0 != p1 or any(t0 < ct <= t1 for ct, _ in s.pump):
            continue
        dt_min = (t1 - t0) / 60.0
        demand = (m.pump_gpm if p0 else 0.0) - m.gal_per_ft * (s.level[i] - s.level[i - 1]) / dt_min
        hour = int((t0 / 3600.0 + EDT_OFFSET_H) % 24)
        expected = m.avg_gpm * float(m.hourly[hour])
        times.append(t1)
        ratio.append(demand / expected)
        sig.append(m.gal_per_ft * np.sqrt(2.0) * m.sigma_l / dt_min / expected)
    nb = int(cfg["refill.baseline_windows"])
    if len(ratio) <= nb:
        return []
    r, sg, tt = np.array(ratio), np.array(sig), np.array(times)
    base = float(np.median(r[:nb]))
    z = (r - base) / sg
    z[:nb] = np.nan
    out = []
    for a, d, b, _, peak in cusum_episodes(z, cfg["refill.k_sigma"], cfg["refill.h_sigma"], two_sided=False):
        out.append(
            Alarm(
                s.station,
                "A7",
                "demand_increase",
                (s.level_id,),
                float(tt[a]),
                float(tt[b]),
                float(tt[d]),
                {
                    "baseline_ratio": round(base, 3),
                    "ratio_at_alarm": round(float(r[d]), 3),
                    "cusum_peak_sigma": round(peak, 3),
                },
                exceedance(peak, cfg["refill.h_sigma"]),
            )
        )
    return out


def baseline_alarms(s: StationStreams, m: SensorModel, alarm_psi: float) -> list[Alarm]:
    """Named baseline: the station low-pressure alarm alone (no spoof guard, no status or mass-balance
    checks)."""
    return [a for a in a7_alarms(s, m, [], alarm_psi) if a.kind == "pressure_loss"]


def detect(s: StationStreams, m: SensorModel, alarm_psi: float) -> list[Alarm]:
    a8 = a8_alarms(s, m)
    return sorted(a8 + a7_alarms(s, m, a8, alarm_psi), key=lambda a: (a.start, a.kind))
