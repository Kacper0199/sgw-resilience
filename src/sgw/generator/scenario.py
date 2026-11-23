"""`generate(scenario)`: truth run, ensembles, reference clocks, water zones, K2 events, truth table and
manifest.

Outputs in `data/fixtures/<scenario>/`: one K9 fixture per feed (`weather`, `oms`, `scada`, `ami`, `fsm`,
`eam`, `lims`, `gis`), `network.json` (named assets, yards, crews), `sections.csv` (footprint network with
fragility), `outages.csv` (truth outage episodes, footprint), `county_hourly.csv` (customers out),
`ensemble.json` (per-advisory members), `truth_table.json` (every seeded case and its outcome, reference
clocks, metrics, validation) and `manifest.json` (sha256 per file, `scenario_sha256` over all of them).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from sgw.common import numbers as numbers_mod
from sgw.contracts.base import utc_iso
from sgw.contracts.fixtures import write_fixture
from sgw.generator import clocks as ck
from sgw.generator import water as wt
from sgw.generator.config import (
    FIXTURES_DIR,
    GENERATOR_NAME,
    GENERATOR_VERSION,
    SYNTHETIC_DIR,
    load_family,
    load_scenario,
    parse_utc,
    rng,
)
from sgw.generator.emit import EventSink, jitter_s, shared_lost, utc
from sgw.generator.ensemble import AdvisoryEnsemble, PointSet, ensemble_record, landfall_eta, run_ensembles
from sgw.generator.restoration import DS_NAMES, median_t50
from sgw.generator.sensitivity import hinge_robustness
from sgw.generator.truth import Truth, access_delay_h, run_truth, wind_kwargs
from sgw.generator.wind import TS_MS, calm_after_peak, epoch, sustained_wind

FEEDS = ("weather", "oms", "scada", "ami", "fsm", "eam", "lims", "gis")
LICENCE = (
    "Apache-2.0 (synthetic data). Inputs: NHC HURDAT2 track (US federal, public domain); county customer "
    "counts EAGLE-I MCC (CC BY 4.0, ORNL, doi:10.6084/m9.figshare.24237376.v4); Census county midpoints"
)


@dataclass
class GenerationResult:
    out_dir: Path
    manifest: dict[str, Any]
    truth_table: dict[str, Any]
    event_count: int


def _fmt(t: float | None) -> str | None:
    return None if t is None or (isinstance(t, float) and math.isnan(t)) else utc_iso(utc(t))


def _region(st: str, fips: str) -> str:
    return f"{st}-{fips}"


def _detail(truth: Truth) -> np.ndarray:
    fips = set(truth.scenario["detail"]["electric_fips"])
    return np.array([f in fips for f in truth.net.sections["fips"]])


def _county_st(truth: Truth) -> dict[str, str]:
    return {c.fips: c.st for c in truth.net.counties}


def weather_events(
    sink: EventSink, truth: Truth, pts: PointSet, ens: list[AdvisoryEnsemble]
) -> dict[str, Any]:
    county_cols = [i for i, k in enumerate(pts.kinds) if k == "county"]
    alert_fips = truth.scenario["detail"]["alert_fips"]
    alert_cols = [pts.ids.index(f) for f in alert_fips]
    st = _county_st(truth)
    issued_alerts: dict[str, float] = {}
    for e in ens:
        issue = epoch(e.advisory.issued)
        onsets = e.official.onset_t[county_cols]
        h0 = float(np.nanmin(onsets)) if np.any(~np.isnan(onsets)) else None
        eta = landfall_eta(truth, e.advisory, e.official.track)
        sink.add(
            "WeatherForecastIssued",
            issue,
            {
                "forecast_id": e.advisory.forecast_id,
                "issuer": "synthetic",
                "advisory_label": e.advisory.label,
                "storm_name": truth.scenario["storm"]["name"],
                "landfall_eta_utc": eta,
                "ts_wind_onset_utc": utc(h0) if h0 is not None else None,
                "max_gust_ms_by_fips": {
                    pts.ids[c]: round(float(e.official.peak_gust[c]), 1) for c in county_cols
                },
                "next_advisory_utc": e.advisory.next_issued,
            },
            key=f"adv-{e.advisory.label}",
            source="nhc-advisory-synthetic",
            issued=issue,
        )
        lead_h = [(e.official.onset_t[c] - issue) / 3600.0 for c in alert_cols]
        lead = min((x for x in lead_h if not math.isnan(x)), default=math.inf)
        for kind, limit in (("watch", 48.0), ("warning", 36.0)):
            if kind not in issued_alerts and 0.0 <= lead <= limit:
                issued_alerts[kind] = issue + 20 * 60.0
    calm = calm_after_peak(truth.point_wind["v1min"], truth.wind_times, TS_MS)
    idx = truth.net.section_index()
    aiken_calm = float(np.nanmax([calm[idx[f"{f}-S1"]] for f in truth.scenario["named"]["feeders"]]))
    warn_t = issued_alerts.get("warning")
    watch_t = issued_alerts.get("watch")
    region = _region(st[alert_fips[0]], alert_fips[0])
    if watch_t is not None and (warn_t is None or watch_t < warn_t):
        sink.add(
            "WeatherAlert",
            watch_t,
            {
                "alert_id": "NWS-SYN-TSW-AIK-01",
                "product": "watch",
                "event_name": "Tropical Storm Watch",
                "severity": "advisory",
                "area_fips": alert_fips,
                "effective_utc": utc(watch_t),
                "expires_utc": utc(warn_t if warn_t is not None else watch_t + 18 * 3600.0),
                "headline": "Tropical Storm Watch (synthetic)",
            },
            key="tsw-01",
            source="nws-alerts",
            region=region,
        )
    if warn_t is not None:
        expires = math.ceil(aiken_calm / 3600.0) * 3600.0
        sink.add(
            "WeatherAlert",
            warn_t,
            {
                "alert_id": "NWS-SYN-TSWARN-AIK-02",
                "product": "warning",
                "event_name": "Tropical Storm Warning",
                "severity": "severe",
                "area_fips": alert_fips,
                "effective_utc": utc(warn_t),
                "expires_utc": utc(expires),
                "headline": "Tropical Storm Warning (synthetic)",
            },
            key="tswarn-02",
            source="nws-alerts",
            region=region,
        )
    return {"watch_utc": _fmt(watch_t), "warning_utc": _fmt(warn_t)}


def electric_events(sink: EventSink, truth: Truth, fam: Any) -> dict[str, Any]:
    net = truth.net
    sc = truth.scenario
    seed = truth.seed
    detail = _detail(truth)
    st = _county_st(truth)
    pins = {c["id"]: c["pin"] for c in sc["seeded"] if isinstance(c.get("pin"), dict)}
    dark = {p["section"] for p in pins.values() if p.get("ami_lost")}
    flood = {p["section"]: int(p["last_gasps"]) for p in pins.values() if "last_gasps" in p}
    late = pins.get("LATE-AMI-BACKLOG")
    if late:
        sink.extra_latency.append(
            (
                "ami-headend",
                epoch(parse_utc(late["from_utc"])),
                epoch(parse_utc(late["to_utc"])),
                int(late["extra_latency_min"]) * 60,
            )
        )
    blocked = access_delay_h(net, truth.section_gust_peak, fam, sc, seed) > 0
    feeder_customers = dict(zip(net.feeders["id"], net.feeders["customers"], strict=True))
    feeder_ami = dict(zip(net.feeders["id"], net.feeders["ami"], strict=True))
    ids = net.sections["id"]
    order = sorted(
        (float(truth.fault_t[j]), ids[j], j) for j in np.flatnonzero(detail & ~np.isnan(truth.fault_t))
    )
    by_section = {a.section: a for a in truth.assignments}
    meters_per = int(fam["telemetry.meters_per_section"])
    p_lost = fam.f("telemetry.ami_last_gasp_lost")
    rho = fam.f("telemetry.evidence_shared_draw_rho")
    meter_no = 0
    counts = {"outages": 0, "last_gasps_dark": 0, "flood_last_gasps": 0}
    for seq, (t_fault, sid, j) in enumerate(order, start=1):
        fid = net.sections["feeder"][j]
        fips = net.sections["fips"][j]
        region = _region(st[fips], fips)
        trunk = bool(net.sections["trunk"][j])
        customers = int(feeder_customers[fid] if trunk else net.sections["customers"][j])
        crit = [c for c in net.sections["critical"][j].split(",") if c]
        out_id = f"OUT-{fid.split('-')[1]}-{utc(t_fault):%m%d}-{seq:04d}"
        wo_id = f"WO-SYN-{fid.split('-')[1]}-{seq:04d}"
        device = net.sections["device"][j]
        kind = "breaker" if trunk else "recloser"
        cause = "tree" if blocked[j] else "wind"
        restore_own = float(truth.restored_t[j])
        restore_eff = float(truth.effective_restore_t[j])
        sink.add(
            "DeviceState",
            t_fault,
            {
                "device_id": device,
                "device_kind": kind,
                "tag": "state",
                "value": "open",
                "unit": None,
                "asset_id": fid,
            },
            key=f"{device}:open:{seq}",
            source="scada-electric",
            region=region,
            domain="electric",
        )
        sink.add(
            "OutageEvent",
            t_fault + 60.0,
            {
                "outage_id": out_id,
                "status": "open",
                "device_id": device,
                "feeder_id": fid,
                "customers_out": customers,
                "cause": cause,
                "critical_facility_ids": crit,
            },
            key=f"{out_id}:open",
            source="oms",
            region=region,
            domain="electric",
        )
        sink.add(
            "WorkOrder",
            t_fault + 600.0,
            {
                "work_order_id": wo_id,
                "status": "open",
                "asset_id": fid,
                "work_type": "storm_restoration",
                "crew_id": None,
                "proposal_id": None,
            },
            key=f"{wo_id}:open",
            source="eam",
            region=region,
            domain="electric",
        )
        a = by_section.get(j)
        if a is not None:
            sink.add(
                "WorkOrder",
                a.assigned,
                {
                    "work_order_id": wo_id,
                    "status": "assigned",
                    "asset_id": fid,
                    "work_type": "storm_restoration",
                    "crew_id": a.crew,
                    "proposal_id": None,
                },
                key=f"{wo_id}:assigned",
                source="eam",
                region=region,
                domain="electric",
            )
            sink.add(
                "WorkOrder",
                a.start,
                {
                    "work_order_id": wo_id,
                    "status": "in_progress",
                    "asset_id": fid,
                    "work_type": "storm_restoration",
                    "crew_id": a.crew,
                    "proposal_id": None,
                },
                key=f"{wo_id}:in_progress",
                source="eam",
                region=region,
                domain="electric",
            )
        if not math.isnan(restore_own):
            sink.add(
                "DeviceState",
                restore_own,
                {
                    "device_id": device,
                    "device_kind": kind,
                    "tag": "state",
                    "value": "closed",
                    "unit": None,
                    "asset_id": fid,
                },
                key=f"{device}:closed:{seq}",
                source="scada-electric",
                region=region,
                domain="electric",
            )
            sink.add(
                "WorkOrder",
                restore_own + 300.0,
                {
                    "work_order_id": wo_id,
                    "status": "closed",
                    "asset_id": fid,
                    "work_type": "storm_restoration",
                    "crew_id": a.crew if a else None,
                    "proposal_id": None,
                },
                key=f"{wo_id}:closed",
                source="eam",
                region=region,
                domain="electric",
            )
        if not math.isnan(restore_eff):
            sink.add(
                "OutageEvent",
                restore_eff + 60.0,
                {
                    "outage_id": out_id,
                    "status": "restored",
                    "device_id": device,
                    "feeder_id": fid,
                    "customers_out": 0,
                    "cause": cause,
                    "critical_facility_ids": crit,
                },
                key=f"{out_id}:restored",
                source="oms",
                region=region,
                domain="electric",
            )
        counts["outages"] += 1
        n_m = flood.get(sid, meters_per)
        lost = shared_lost(seed, sid, n_m, p_lost, rho)
        ami_share = float(feeder_ami[fid])
        for m in range(n_m):
            meter_no += 1
            meter = f"MTR-{fid.split('-')[1]}-{70000 + meter_no}"
            premise = f"PRM-{fid.split('-')[1]}-{50000 + meter_no}"
            has_ami = rng(seed, "ami_has", meter).uniform() < ami_share
            if sid in dark or not has_ami or lost[m]:
                counts["last_gasps_dark"] += int(sid in dark)
                continue
            if sid in flood:
                counts["flood_last_gasps"] += 1
            sink.add(
                "MeterEvent",
                t_fault + jitter_s(seed, meter, "gasp"),
                {"meter_id": meter, "kind": "last_gasp", "premise_id": premise, "feeder_id": fid},
                key=f"{meter}:gasp",
                source="ami-headend",
                region=region,
                domain="electric",
            )
            if not math.isnan(restore_eff):
                sink.add(
                    "MeterEvent",
                    restore_eff + jitter_s(seed, meter, "restore"),
                    {"meter_id": meter, "kind": "power_restore", "premise_id": premise, "feeder_id": fid},
                    key=f"{meter}:restore",
                    source="ami-headend",
                    region=region,
                    domain="electric",
                )
    counts["late_ami"] = sink.delayed
    return counts


def crew_events(sink: EventSink, truth: Truth) -> dict[str, Any]:
    sc = truth.scenario
    net = truth.net
    st = _county_st(truth)
    detail_yards = set(sc["named"]["detail_yards"])
    yard_by_idx = {i: y for i, y in enumerate(net.yards)}
    avail = epoch(parse_utc(sc["detail"]["crew_pre_storm_available_utc"]))
    staged = epoch(parse_utc(sc["detail"]["crew_pre_storm_staged_utc"]))
    request = epoch(parse_utc(sc["detail"]["mutual_aid_request_utc"]))
    calm = calm_after_peak(
        truth.point_wind["v1min"], truth.wind_times, truth.family.f("restoration.bucket_limit_sustained_ms")
    )
    crews = [c for c in truth.crews if yard_by_idx[c.yard]["id"] in detail_yards]
    jobs: dict[str, list[Any]] = {}
    for a in truth.assignments:
        jobs.setdefault(a.crew, []).append(a)
    n_blocked = 0
    for c in crews:
        y = yard_by_idx[c.yard]
        region = _region(st[y["fips"]], y["fips"])

        def emit(
            t: float,
            status: str,
            loc: str | None,
            key: str,
            reason: str | None = None,
            crew: Any = c,
            region: str = region,
        ) -> None:
            sink.add(
                "CrewStatus",
                t,
                {
                    "crew_id": crew.id,
                    "status": status,
                    "location_id": loc,
                    "headcount": crew.headcount,
                    "block_reason": reason,
                },
                key=f"{crew.id}:{key}",
                source="fsm-crews",
                region=region,
                domain="electric",
            )

        if c.mutual_aid:
            emit(request + 3600.0, "enroute", y["id"], "ma-enroute")
            emit(c.available_utc, "staged", y["id"], "ma-staged")
        else:
            emit(avail + jitter_s(truth.seed, c.id, "avail", high=600.0), "available", None, "available")
            emit(staged + jitter_s(truth.seed, c.id, "staged", high=600.0), "staged", y["id"], "staged")
        for k, a in enumerate(jobs.get(c.id, [])):
            loc = net.sections["feeder"][a.section]
            emit(a.assigned, "enroute", loc, f"{k}:enroute")
            if a.start - a.arrive > 300.0:
                windy = calm[a.section] > a.arrive
                emit(
                    a.arrive,
                    "blocked",
                    loc,
                    f"{k}:blocked",
                    "wind_above_bucket_limit" if windy else "road_closed",
                )
                n_blocked += 1
            emit(a.start, "onsite", loc, f"{k}:onsite")
            emit(a.end, "done", loc, f"{k}:done")
    return {"detail_crews": sorted(c.id for c in crews), "blocked_events": n_blocked}


def water_runs(truth: Truth) -> list[wt.ZoneRun]:
    sc = truth.scenario
    idx = truth.net.section_index()
    secs = [f"{ps['feeder']}-S1" for ps in sc["named"]["pump_stations"].values()]
    fault = {s: (None if math.isnan(truth.fault_t[idx[s]]) else float(truth.fault_t[idx[s]])) for s in secs}
    rest = {
        s: (None if math.isnan(truth.restored_t[idx[s]]) else float(truth.restored_t[idx[s]])) for s in secs
    }
    cols = [idx[s] for s in secs]
    v = truth.point_wind["v1min"][:, cols]
    calm = dict(zip(secs, calm_after_peak(v, truth.wind_times, TS_MS).tolist(), strict=True))
    peak = dict(zip(secs, truth.wind_times[np.argmax(v, axis=0)].tolist(), strict=True))
    t0 = epoch(parse_utc(sc["telemetry_window"]["start_utc"]))
    t1 = epoch(parse_utc(sc["telemetry_window"]["end_utc"]))
    return [
        wt.simulate_zone(s, truth.family, t0, t1, truth.seed)
        for s in wt.zone_specs(sc, fault, rest, peak, calm)
    ]


def water_events(sink: EventSink, truth: Truth, runs: list[wt.ZoneRun]) -> dict[str, Any]:
    sc = truth.scenario
    fam = truth.family
    seed = truth.seed
    region = "SC-45003"
    pins = {c["id"]: c["pin"] for c in sc["seeded"] if isinstance(c.get("pin"), dict)}
    hosp = sc["named"]["hospital"]
    noise_p = fam.f("water.pressure_noise_psi")
    noise_l = fam.f("water.level_noise_ft")
    gal_per_ft, _ = wt.tank_geometry(fam)
    outcomes: dict[str, Any] = {}
    wo_seq = 0
    for run in runs:
        spec = run.spec
        ps = spec.station
        code = ps.replace("-", "")
        sample = np.arange(0, len(run.t), 15)
        t15 = run.t[sample]
        pt_id = f"PT-{code}-DISCH"
        lt_id = f"LT-{spec.tank}"
        r = rng(seed, "sensor", pt_id)
        pt = np.round(run.pressure[sample] + r.normal(0.0, noise_p, len(sample)), 1)
        lt = np.round(
            run.volume[sample] / gal_per_ft + rng(seed, "sensor", lt_id).normal(0.0, noise_l, len(sample)), 1
        )
        pt, lt = _sensor_faults(pins, code, t15, pt, lt)
        for k, t in enumerate(t15):
            sink.add(
                "DeviceState",
                float(t),
                {
                    "device_id": pt_id,
                    "device_kind": "pressure_sensor",
                    "tag": "discharge_pressure",
                    "value": float(pt[k]),
                    "unit": "psi",
                    "asset_id": ps,
                },
                key=f"{pt_id}:{k}",
                source="scada-water",
                region=region,
                domain="water",
            )
            if k % 2 == 0:
                sink.add(
                    "DeviceState",
                    float(t),
                    {
                        "device_id": lt_id,
                        "device_kind": "tank",
                        "tag": "level",
                        "value": float(max(lt[k], 0.0)),
                        "unit": "ft",
                        "asset_id": spec.tank,
                    },
                    key=f"{lt_id}:{k}",
                    source="scada-water",
                    region=region,
                    domain="water",
                )
        if spec.zone == hosp["zone"]:
            hp = np.round(
                run.pressure[sample]
                - fam.f("water.hospital_pressure_offset_psi")
                + rng(seed, "sensor", hosp["pressure_sensor"]).normal(0.0, noise_p, len(sample)),
                1,
            )
            for k, t in enumerate(t15):
                sink.add(
                    "DeviceState",
                    float(t),
                    {
                        "device_id": hosp["pressure_sensor"],
                        "device_kind": "pressure_sensor",
                        "tag": "service_pressure",
                        "value": float(hp[k]),
                        "unit": "psi",
                        "asset_id": hosp["id"],
                    },
                    key=f"{hosp['pressure_sensor']}:{k}",
                    source="scada-water",
                    region=region,
                    domain="water",
                )
        pump = f"PMP-{ps}-1"
        prev = None
        for i in range(len(run.t)):
            if run.pump_on[i] != prev:
                sink.add(
                    "DeviceState",
                    float(run.t[i]),
                    {
                        "device_id": pump,
                        "device_kind": "pump",
                        "tag": "running",
                        "value": bool(run.pump_on[i]),
                        "unit": None,
                        "asset_id": ps,
                    },
                    key=f"{pump}:{i}",
                    source="scada-water",
                    region=region,
                    domain="water",
                )
                prev = run.pump_on[i]
        for k, (t, dev, state) in enumerate(run.gen_events):
            if dev == "FTK-WREN-3":
                wo_seq += 1 if state.startswith("requested") else 0
                wo = f"WO-SYN-FUEL-{wo_seq:02d}"
                gen = state.split(":", 1)[1]
                sink.add(
                    "WorkOrder",
                    t,
                    {
                        "work_order_id": wo,
                        "status": "open" if state.startswith("requested") else "closed",
                        "asset_id": gen,
                        "work_type": "fuel_delivery",
                        "crew_id": None,
                        "proposal_id": None,
                    },
                    key=f"{wo}:{state.split(':')[0]}",
                    source="eam",
                    region=region,
                    domain="water",
                )
                continue
            if dev == "MGEN-HALBERD-500":
                status = {"dispatched": "open", "running": "in_progress", "demobilised": "closed"}.get(state)
                if status:
                    sink.add(
                        "WorkOrder",
                        t,
                        {
                            "work_order_id": "WO-SYN-PS17-GEN-01",
                            "status": status,
                            "asset_id": ps,
                            "work_type": "portable_generator_hookup",
                            "crew_id": None,
                            "proposal_id": None,
                        },
                        key=f"WO-SYN-PS17-GEN-01:{status}",
                        source="eam",
                        region=region,
                        domain="water",
                    )
                if state == "dispatched":
                    continue
            sink.add(
                "DeviceState",
                t,
                {
                    "device_id": dev,
                    "device_kind": "generator",
                    "tag": "state",
                    "value": state,
                    "unit": None,
                    "asset_id": ps,
                },
                key=f"{dev}:state:{k}",
                source="scada-water",
                region=region,
                domain="water",
            )
        for gen, series in run.fuel.items():
            if not gen:
                continue
            hourly = np.arange(0, len(run.t), 60)
            for i in hourly:
                if not math.isnan(series[i]) and run.source[i] == "generator":
                    sink.add(
                        "DeviceState",
                        float(run.t[i]),
                        {
                            "device_id": gen,
                            "device_kind": "generator",
                            "tag": "fuel_gal",
                            "value": round(float(series[i]), 1),
                            "unit": "gal",
                            "asset_id": ps,
                        },
                        key=f"{gen}:fuel:{i}",
                        source="scada-water",
                        region=region,
                        domain="water",
                    )
        floor = fam.f("water.floor_psi")
        below = run.first_below(floor)
        back = run.first_at_or_above(floor, below) if below is not None else None
        outcomes[ps] = {
            "grid_loss_utc": _fmt(spec.grid_loss_t),
            "grid_restore_utc": _fmt(spec.grid_restore_t),
            "below_floor_utc": _fmt(below),
            "back_above_floor_utc": _fmt(back),
            "min_pressure_psi": round(float(run.pressure.min()), 1),
            "generator_events": [[_fmt(t), d, s] for t, d, s in run.gen_events],
        }
    outcomes["hospital"] = hospital_events(sink, truth)
    lims_events(sink, truth, runs, outcomes)
    return outcomes


def _sensor_faults(
    pins: dict[str, Any], code: str, t: np.ndarray, pt: np.ndarray, lt: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    pt = pt.copy()
    lt = lt.copy()
    for cid, pin in pins.items():
        if not cid.startswith(f"FAULT-{code}-"):
            continue
        start = epoch(parse_utc(pin["from_utc"]))
        end = start + float(pin.get("duration_h", 0.0)) * 3600.0
        win = (t >= start) & (t < end)
        if cid.endswith("STUCK-LEVEL") and win.any():
            lt[win] = lt[np.argmax(win)]
        elif cid.endswith("DRIFT"):
            pt = np.where(win, np.round(pt + (t - start) / 3600.0 * float(pin["psi_per_h"]), 1), pt)
        elif cid.endswith("REPLAY-SPOOF"):
            src = epoch(parse_utc(pin["replay_of_utc"]))
            shift = int(round((start - src) / 900.0))
            k = np.flatnonzero(win)
            pt[k] = pt[k - shift]
    return pt, lt


def hospital_events(sink: EventSink, truth: Truth) -> dict[str, Any]:
    hosp = truth.scenario["named"]["hospital"]
    j = truth.net.section_index()[f"{hosp['feeder']}-S1"]
    loss, back = float(truth.fault_t[j]), float(truth.effective_restore_t[j])
    if math.isnan(loss):
        return {"grid_loss_utc": None, "generator": "standby"}
    region = "SC-45003"
    sink.add(
        "DeviceState",
        loss + 30.0,
        {
            "device_id": hosp["generator"],
            "device_kind": "generator",
            "tag": "state",
            "value": "running",
            "unit": None,
            "asset_id": hosp["id"],
        },
        key=f"{hosp['generator']}:running",
        source="scada-water",
        region=region,
        domain="water",
    )
    if not math.isnan(back):
        sink.add(
            "DeviceState",
            back + 60.0,
            {
                "device_id": hosp["generator"],
                "device_kind": "generator",
                "tag": "state",
                "value": "standby",
                "unit": None,
                "asset_id": hosp["id"],
            },
            key=f"{hosp['generator']}:standby",
            source="scada-water",
            region=region,
            domain="water",
        )
    return {"grid_loss_utc": _fmt(loss), "grid_back_utc": _fmt(back), "generator": hosp["generator"]}


def lims_events(sink: EventSink, truth: Truth, runs: list[wt.ZoneRun], outcomes: dict[str, Any]) -> None:
    sc = truth.scenario
    t0 = epoch(parse_utc(sc["telemetry_window"]["start_utc"]))
    t1 = epoch(parse_utc(sc["telemetry_window"]["end_utc"]))
    for run in runs:
        zone = run.spec.zone
        short = zone.split("-")[-1][:6]
        day = t0 + 14 * 3600.0
        while day < t1:
            r = rng(truth.seed, "lims", zone, day)
            sid = f"LIMS-SYN-{short}-{utc(day):%m%d}"
            sink.add(
                "WaterQualitySample",
                day,
                {
                    "sample_id": sid,
                    "zone_id": zone,
                    "analyte": "chlorine_residual",
                    "result": "within_range",
                    "value": round(float(np.clip(r.normal(1.1, 0.12), 0.6, 1.6)), 2),
                    "unit": "mg/L",
                },
                key=sid,
                source="lims",
                region="SC-45003",
                domain="water",
            )
            day += 86400.0
        back = outcomes[run.spec.station]["back_above_floor_utc"]
        if back:
            for k, hours in enumerate((24, 48), start=1):
                t = epoch(parse_utc(back)) + hours * 3600.0
                sid = f"LIMS-SYN-{short}-TC{k}"
                sink.add(
                    "WaterQualitySample",
                    t,
                    {
                        "sample_id": sid,
                        "zone_id": zone,
                        "analyte": "total_coliform",
                        "result": "absent",
                        "value": None,
                        "unit": None,
                    },
                    key=sid,
                    source="lims",
                    region="SC-45003",
                    domain="water",
                )


def gis_events(sink: EventSink, truth: Truth) -> None:
    sc = truth.scenario
    hosp = sc["named"]["hospital"]
    t = epoch(parse_utc("2024-09-26T09:30:00Z"))
    for ps_id, ps in sc["named"]["pump_stations"].items():
        num = ps["feeder"].split("-")[-1]
        cross = [ps_id] + ([hosp["id"]] if ps["zone"] == hosp["zone"] else [])
        sink.add(
            "NetworkTrace",
            t,
            {
                "trace_id": f"TRC-FDR{num}-{ps_id.replace('-', '')}",
                "source_id": ps["feeder"],
                "downstream_ids": [ps_id, ps["zone"]],
                "cross_domain_ids": cross,
            },
            key=f"trace-{ps_id}",
            source="gis-trace",
            region="SC-45003",
            domain="electric",
        )


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def dump_json(path: Path, data: Any, compact: bool = False) -> None:
    if compact:
        text = json.dumps(data, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    else:
        text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def tables(out: Path, truth: Truth) -> None:
    net = truth.net
    s = net.sections
    write_csv(
        out / "sections.csv",
        [
            "section_id",
            "feeder_id",
            "fips",
            "lat",
            "lon",
            "customers",
            "trunk",
            "device_id",
            "theta_known_ms",
            "capacity_ms",
            "critical_ids",
        ],
        [
            [
                s["id"][j],
                s["feeder"][j],
                s["fips"][j],
                round(float(s["lat"][j]), 4),
                round(float(s["lon"][j]), 4),
                int(s["customers"][j]),
                int(bool(s["trunk"][j])),
                s["device"][j],
                round(float(s["theta_known"][j]), 2),
                round(float(s["capacity"][j]), 2),
                s["critical"][j],
            ]
            for j in range(len(s["id"]))
        ],
    )
    rows = []
    for j in np.flatnonzero(~np.isnan(truth.fault_t)):
        rows.append(
            [
                s["id"][j],
                s["feeder"][j],
                s["fips"][j],
                int(s["customers"][j]),
                _fmt(truth.fault_t[j]),
                round(float(truth.section_gust_peak[j]), 1),
                DS_NAMES[truth.ds[j]],
                _fmt(truth.work_ok[j]),
                _fmt(truth.restored_t[j]),
                _fmt(truth.effective_restore_t[j]),
            ]
        )
    rows.sort(key=lambda r: (r[4], r[0]))
    write_csv(
        out / "outages.csv",
        [
            "section_id",
            "feeder_id",
            "fips",
            "customers",
            "fault_utc",
            "peak_gust_ms",
            "damage_state",
            "work_ok_utc",
            "repaired_utc",
            "customers_back_utc",
        ],
        rows,
    )
    customers = np.asarray(s["customers"], dtype=float)
    fips = np.asarray(s["fips"])
    hourly = np.arange(0, len(truth.times), 4)
    crow = []
    for c in net.counties:
        cols = fips == c.fips
        series = (truth.out[hourly][:, cols] * customers[cols][None, :]).sum(axis=1)
        crow += [[c.fips, _fmt(truth.times[h]), int(v)] for h, v in zip(hourly, series, strict=True) if v > 0]
    write_csv(out / "county_hourly.csv", ["fips", "hour_utc", "customers_out"], crow)


def network_json(truth: Truth) -> dict[str, Any]:
    sc = truth.scenario
    yard_ids = [y["id"] for y in truth.net.yards]
    return {
        "label": "synthetic",
        "named": sc["named"],
        "yards": truth.net.yards,
        "crews": [
            {
                "crew_id": c.id,
                "yard": yard_ids[c.yard],
                "headcount": c.headcount,
                "mutual_aid": c.mutual_aid,
                "available_utc": _fmt(c.available_utc),
            }
            for c in truth.crews
        ],
        "county_codes": truth.net.county_code,
        "feeders": {"count": len(truth.net.feeders["id"]), "sections": len(truth.net.sections["id"])},
    }


def validation(truth: Truth) -> dict[str, Any]:
    ref_path = SYNTHETIC_DIR / "validation" / "helene_eaglei_county.csv"
    with ref_path.open(encoding="utf-8") as fh:
        ref = {r["fips"].zfill(5): r for r in csv.DictReader(fh)}
    common = sorted(set(ref) & set(truth.county))
    syn_frac = [truth.county[f]["peak_frac"] for f in common]
    obs_frac = [float(ref[f]["peak_frac"]) for f in common]
    syn_t90 = [truth.county[f]["t90_h"] for f in common if not math.isnan(truth.county[f]["t90_h"])]
    obs_t90 = [float(ref[f]["t90_h"]) for f in common if ref[f]["t90_h"]]
    customers = np.asarray(truth.net.sections["customers"], dtype=float)
    total = (truth.out * customers[None, :]).sum(axis=1)
    ip = int(np.argmax(total))
    obs_peak = float(numbers_mod.value("helene_footprint_peak_out"))
    stations = {
        "AGS": (33.37, -81.96, 36.5, "2024-09-27T09:00:00Z"),
        "SAV": (32.12, -81.20, 34.0, "2024-09-27T07:00:00Z"),
    }
    lat = np.array([v[0] for v in stations.values()])
    lon = np.array([v[1] for v in stations.values()])
    v = sustained_wind(truth.track, truth.wind_times, lat, lon, **wind_kwargs(truth.family))
    g = truth.family.f("wind.gust_factor") * v
    asos = {}
    for k, (name, (_, _, obs, obs_t)) in enumerate(stations.items()):
        i = int(np.argmax(g[:, k]))
        asos[name] = {
            "model_peak_gust_ms": round(float(g[i, k]), 1),
            "model_peak_utc": _fmt(truth.wind_times[i]),
            "observed_peak_gust_ms": obs,
            "observed_peak_utc": obs_t,
            "bias_pct": round(100.0 * (float(g[i, k]) - obs) / obs, 1),
        }
    return {
        "note": "validation, not calibration: EAGLE-I Helene county table and ASOS peaks fit no "
        "parameter (t50 is the one calibration target)",
        "footprint_peak_out": {
            "synthetic": int(total[ip]),
            "synthetic_utc": _fmt(truth.times[ip]),
            "observed": int(obs_peak),
            "observed_source": "numbers.yaml helene_footprint_peak_out",
            "error_pct": round(100.0 * (total[ip] - obs_peak) / obs_peak, 1),
        },
        "county_peak_fraction": {
            "n": len(common),
            "synthetic_median": round(float(np.median(syn_frac)), 3),
            "observed_median": round(float(np.median(obs_frac)), 3),
            "spearman": round(float(spearmanr(syn_frac, obs_frac)[0]), 3),
            "observed_capped_counties": sum(int(ref[f].get("frac_capped", 0) or 0) for f in common),
            "mae": round(float(np.mean(np.abs(np.array(syn_frac) - np.array(obs_frac)))), 3),
        },
        "county_t90_h": {
            "synthetic_median": round(float(np.median(syn_t90)), 1),
            "observed_median": round(float(np.median(obs_t90)), 1),
            "within_25pct": bool(abs(np.median(syn_t90) / np.median(obs_t90) - 1.0) <= 0.25),
        },
        "asos_peak_gust": asos,
    }


def seeded_outcomes(
    truth: Truth,
    clocks: dict[str, Any],
    water: dict[str, Any],
    electric: dict[str, Any],
    crews: dict[str, Any],
    weather: dict[str, Any],
    ens: list[AdvisoryEnsemble],
) -> list[dict[str, Any]]:
    sc = truth.scenario
    idx = truth.net.section_index()

    def sec(sid: str) -> dict[str, Any]:
        j = idx[sid]
        return {
            "section": sid,
            "capacity_ms": round(float(truth.net.sections["capacity"][j]), 1),
            "peak_gust_ms": round(float(truth.section_gust_peak[j]), 1),
            "fault_utc": _fmt(truth.fault_t[j]),
            "damage_state": DS_NAMES[truth.ds[j]],
            "repaired_utc": _fmt(truth.restored_t[j]),
            "customers_back_utc": _fmt(truth.effective_restore_t[j]),
        }

    n, n1 = clocks.get("N"), clocks.get("N+1")
    out = []
    for case in sc["seeded"]:
        cid = case["id"]
        o: dict[str, Any] = {}
        if cid == "HINGE-PS17-N-N1" and n and n1:
            p_n, p_n1 = n["cases"][ck.CASE_POWER], n1["cases"][ck.CASE_POWER]
            o = {
                "decide_by_N_utc": p_n["clock"]["decide_by_utc"],
                "decide_by_N1_utc": p_n1["clock"]["decide_by_utc"],
                "effective_decide_by_N_utc": p_n["effective_decide_by_utc"],
                "effective_decide_by_N1_utc": p_n1["effective_decide_by_utc"],
                "quoted": "effective",
                "quoted_note": "the generated helene scenario is the story of record (UI, documents, "
                "video); quote "
                "the effective, critical-path-bound decide-by; helene_micro is for thin-slice tests only",
                "shift_min": ck.shift_minutes(n, n1),
                "effective_shift_min": ck.shift_minutes(n, n1, effective=True),
                "no_regret_share_ppm": [p_n["no_regret_share_ppm"], p_n1["no_regret_share_ppm"]],
                "verdict": [p_n["no_regret_verdict"], p_n1["no_regret_verdict"]],
                "ps17_p_loss_ppm": [n["ps17_p_loss_ppm"], n1["ps17_p_loss_ppm"]],
                "official_error_pinned": [e.pinned for e in ens if e.advisory.label in ("N", "N+1")],
                "consequence_N1_p10_p50_p90_utc": [
                    p_n1["clock"]["consequence_p10_utc"],
                    p_n1["clock"]["consequence_utc"],
                    p_n1["clock"]["consequence_p90_utc"],
                ],
                "realized_power_loss_utc": water["PS-17"]["grid_loss_utc"],
                "realized_floor_crossing_utc": water["PS-17"]["below_floor_utc"],
                "note": "forecast exposure (P(loss) >= material_loss_p) precedes the realized trip, so the "
                "reference clock is conservative against this truth draw",
            }
        elif cid == "CP-PS17-CHAIN" and n1:
            o = {
                "edges": [[p, d] for d, pre in ck.PREREQUISITES.items() for p in pre],
                "effective_decide_by_N1_utc": {
                    k: v["effective_decide_by_utc"] for k, v in n1["cases"].items()
                },
                "bound_by_N1": n1["bound_by"],
                "on_critical_path_N1": {k: v["on_critical_path"] for k, v in n1["cases"].items()},
            }
        elif case["kind"] in ("fragility_pin", "telemetry_pin") and "section" in case.get("pin", {}):
            o = sec(case["pin"]["section"])
            if cid == "W9-AMI-DARK-SECTION":
                o["last_gasps_emitted"] = 0
                o["meters_suppressed"] = electric["last_gasps_dark"]
            if cid == "AMI-FLOOD-ONE-RECLOSER":
                o["last_gasps_emitted"] = electric["flood_last_gasps"]
            if cid == "D7-PRIORITY-CONFLICT":
                o["ps17_feeder"] = sec("FDR-AIK-2207-S1")
        elif cid == "D6-HOSPITAL-POWER-NO-PRESSURE":
            o = {"zone": water["PS-17"], "hospital": water["hospital"]}
        elif cid == "D2-GENERATOR-FAILS-H30":
            o = {"zone": water["PS-52"], "feeder": sec(case["pin"]["section"])}
        elif cid == "D3-FUEL-TRUCK-FLOOD-BLOCK":
            o = {"zone": water["PS-38"], "feeder": sec(case["pin"]["section"])}
        elif cid == "GOV-ADVISORY-DURING-T3":
            adv = next((e for e in ens if e.advisory.label == "N+1"), None)
            o = {
                "advisory_N1_issued_utc": utc_iso(adv.advisory.issued) if adv else None,
                "expected": "material proposal update voids APR-CREW-V1-IC (platform, helene_micro)",
            }
        elif cid == "LATE-AMI-BACKLOG":
            o = {
                "extra_latency_min": case["pin"]["extra_latency_min"],
                "events_delayed": electric["late_ami"],
            }
        elif case["kind"] == "water_fault":
            o = {"window_from_utc": case["pin"]["from_utc"], "duration_h": case["pin"].get("duration_h")}
        out.append({**case, "outcome": o})
    return out


def generate(scenario_name: str = "helene", out_dir: Path | None = None) -> GenerationResult:
    sc = load_scenario(scenario_name)
    fam = load_family(sc["family"])
    out = out_dir or FIXTURES_DIR / scenario_name
    out.mkdir(parents=True, exist_ok=True)
    truth = run_truth(sc, fam)
    pts, ens = run_ensembles(truth)
    clocks = {e.advisory.label: c for e in ens if (c := ck.advisory_clocks(e, pts, fam)) is not None}
    runs = water_runs(truth)
    w0 = epoch(parse_utc(sc["window"]["start_utc"]))
    w1 = epoch(parse_utc(sc["window"]["end_utc"]))
    sink = EventSink(scenario_name, fam, (w0, w1))
    weather = weather_events(sink, truth, pts, ens)
    electric = electric_events(sink, truth, fam)
    crews = crew_events(sink, truth)
    water = water_events(sink, truth, runs)
    gis_events(sink, truth)
    header = {
        "fixture": scenario_name,
        "schema_version": 1,
        "feed_mode": "synthetic",
        "generator": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "seed": int(sc["seed"]),
        "calibration_source": "family A (data/synthetic/family_a.yaml); repair scale calibrated to Helene "
        "county t50 35.5 h (numbers.yaml); track NHC HURDAT2 AL092024",
        "scenario_window": {"start_utc": sc["window"]["start_utc"], "end_utc": sc["window"]["end_utc"]},
        "licence": LICENCE,
        "hand_made": False,
        "data_label": "synthetic",
        "note": "Generated by `uv run sgw data generate --scenario helene`. Every value is synthetic.",
    }
    files: dict[str, dict[str, Any]] = {}
    for feed in FEEDS:
        h = write_fixture(out / f"{feed}.jsonl", {**header, "feed": feed}, sink.by_feed.get(feed, []))
        files[f"{feed}.jsonl"] = {"body_sha256": h.body_sha256, "events": len(sink.by_feed.get(feed, []))}
    tables(out, truth)
    dump_json(out / "network.json", network_json(truth))
    dump_json(
        out / "ensemble.json",
        {
            "label": "synthetic",
            "points": {
                "ids": pts.ids,
                "kinds": pts.kinds,
                "lat": [round(float(x), 4) for x in pts.lat],
                "lon": [round(float(x), 4) for x in pts.lon],
            },
            "advisories": [ensemble_record(pts, e, fam.f("clocks.no_regret_member_p_loss")) for e in ens],
        },
        compact=True,
    )
    customers = np.asarray(truth.net.sections["customers"], dtype=float)
    metrics = {
        "county_t50_median_h": median_t50(truth.county),
        "county_t50_target_h": float(numbers_mod.value("helene_restoration_t50_hours")),
        "county_t90_median_h": float(np.nanmedian([m["t90_h"] for m in truth.county.values()])),
        "counties_with_outage": len(truth.county),
        "sections_failed": int((~np.isnan(truth.fault_t)).sum()),
        "cumulative_customers_out": int(customers[~np.isnan(truth.fault_t)].sum()),
        "crew_groups_internal": sum(not c.mutual_aid for c in truth.crews),
        "crew_groups_mutual_aid": sum(c.mutual_aid for c in truth.crews),
        "personnel_total": sum(c.headcount for c in truth.crews),
        "events": sink.count(),
        "events_outside_window_dropped": sink.dropped_outside_window,
    }
    truth_table = {
        "scenario": scenario_name,
        "family": fam.name,
        "seed": int(sc["seed"]),
        "label": "synthetic",
        "generator": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "seeded_cases": seeded_outcomes(truth, clocks, water, electric, crews, weather, ens),
        "critical_path": {
            "nodes": list(ck.PREREQUISITES),
            "edges": [[p, d] for d, pre in ck.PREREQUISITES.items() for p in pre],
        },
        "clocks_by_advisory": clocks,
        "alerts": weather,
        "crews": crews,
        "water": water,
        "metrics": metrics,
        "validation": validation(truth),
        "hinge_robustness": hinge_robustness(truth),
        "ids": {
            "detail_feeders": sorted(
                {
                    f
                    for f, fp in zip(truth.net.feeders["id"], truth.net.feeders["fips"], strict=True)
                    if fp in sc["detail"]["electric_fips"]
                }
            ),
            "pump_stations": sorted(sc["named"]["pump_stations"]),
            "advisories": [e.advisory.forecast_id for e in ens],
        },
    }
    dump_json(out / "truth_table.json", truth_table)
    for name in (
        "sections.csv",
        "outages.csv",
        "county_hourly.csv",
        "network.json",
        "ensemble.json",
        "truth_table.json",
    ):
        files[name] = {}
    for name in files:
        files[name]["sha256"] = hashlib.sha256((out / name).read_bytes()).hexdigest()
    combined = hashlib.sha256(
        "".join(f"{k}:{files[k]['sha256']}\n" for k in sorted(files)).encode()
    ).hexdigest()
    manifest = {
        "scenario": scenario_name,
        "family": fam.name,
        "seed": int(sc["seed"]),
        "generator_version": GENERATOR_VERSION,
        "files": files,
        "scenario_sha256": combined,
    }
    dump_json(out / "manifest.json", manifest)
    return GenerationResult(out, manifest, truth_table, sink.count())
