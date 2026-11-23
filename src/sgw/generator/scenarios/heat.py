"""Heatwave scenario (S-HEAT, 2024-07-13..17 Eastern): footprint heat trigger on real station Tmax,
transformer hot-spot table for the stressed Aiken units (IEC 60076-7 on AGS ambient), the H2 seeded
insight (still air: the FDR-AIK-2219 trunk limit binds before TX-BRAMBLEGATE-T2) and a synthetic Heat
Advisory (K9 `weather.jsonl`)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sgw.contracts.vocab import Tier
from sgw.generator.scenarios import common as cm
from sgw.generator.scenarios.weather import AGS_HOURLY, STATIONS_DAILY, load_daily, load_hourly
from sgw.generator.wind import epoch
from sgw.models.heat import hotspot as hs

SCENARIO = "heat"
WINDOW = (datetime(2024, 7, 13, 4, tzinfo=UTC), datetime(2024, 7, 18, 4, tzinfo=UTC))
SPIN_UP_START = datetime(2024, 7, 10, 4, tzinfo=UTC)
ALERT_FIPS = ["13245", "45003"]
HOT_SPOT_HEADER = (
    "asset_id",
    "site",
    "cooling",
    "rating_kva",
    "protected_load",
    "k_base",
    "k_peak",
    "theta_a_at_peak_c",
    "theta_o_peak_c",
    "theta_h_peak_c",
    "peak_utc",
    "hours_ge_110c",
    "hours_ge_120c",
    "faa_peak",
    "aging_equiv_days",
    "night_min_theta_h_c",
    "first_warning_utc",
    "warning_before_trigger",
    "alarm",
)


def trigger() -> hs.HeatTrigger:
    return hs.heat_trigger([(d.station, d.day, d.tmax_c) for d in load_daily(STATIONS_DAILY)])


def _first_warning(res: hs.UnitResult) -> datetime | None:
    warn = float(hs.value("alarms", "warning_c"))
    return next((t for t, h in zip(res.times, res.trace.theta_h, strict=True) if h >= warn), None)


def build(out: Path) -> dict[str, Any]:
    trig = trigger()
    fires = trig.fires_in(*(t.astimezone(hs.EASTERN).date() for t in WINDOW))
    fire_utc = hs.local_midnight_utc(fires[0]) if fires else None
    grid = hs.minute_grid(load_hourly(AGS_HOURLY), SPIN_UP_START, WINDOW[1])
    results = {str(u["asset_id"]): hs.run_unit(u, grid) for u in hs.params()["units"]}
    rows: list[list[Any]] = []
    table: list[dict[str, Any]] = []
    for aid, res in results.items():
        s = hs.summarise(res, *WINDOW)
        first = _first_warning(res)
        s["first_warning_utc"] = first
        s["warning_before_trigger"] = first is not None and fire_utc is not None and first < fire_utc
        s["protected_load"] = bool(res.unit.get("protected_load", False))
        table.append(s)
        rows.append(
            [
                aid,
                s["site"],
                s["cooling"],
                s["rating_kva"],
                str(s["protected_load"]).lower(),
                s["k_base"],
                f"{s['k_peak']:.3f}",
                f"{s['theta_a_at_peak_c']:.1f}",
                f"{s['theta_o_peak_c']:.1f}",
                f"{s['theta_h_peak_c']:.1f}",
                cm.iso(s["peak_utc"]),
                f"{s['hours_ge_watch']:.1f}",
                f"{s['hours_ge_warning']:.1f}",
                f"{s['faa_peak']:.2f}",
                f"{s['aging_equiv_days']:.2f}",
                f"{s['night_min_theta_h_c']:.1f}",
                cm.iso(first) if first else "",
                str(s["warning_before_trigger"]).lower(),
                s["alarm"],
            ]
        )
    rows.sort(key=lambda r: (-float(r[9]), r[0]))
    cm.write_csv(out / "hot_spot.csv", HOT_SPOT_HEADER, rows)
    line = hs.params()["line"]
    tx = results[str(line["transformer_id"])]
    rating = hs.binding_check(tx, grid, *WINDOW, float(hs.value("wind", "rating_basis_ms")))
    still = hs.binding_check(tx, grid, *WINDOW, float(hs.value("wind", "still_air_ms")))

    def case(b: hs.BindingCheck) -> dict[str, Any]:
        return {
            "wind_case": b.wind_case,
            "binding": b.binding,
            "line_limit_utc": cm.iso(b.line_limit_utc) if b.line_limit_utc else None,
            "transformer_warning_utc": cm.iso(b.transformer_limit_utc) if b.transformer_limit_utc else None,
            "peak_line_loading_pct": cm.r(b.peak_line_loading_pct, 1),
            "peak_line_loading_utc": cm.iso(b.peak_line_loading_utc),
        }

    lead_h = (
        (still.transformer_limit_utc - still.line_limit_utc).total_seconds() / 3600.0
        if still.transformer_limit_utc and still.line_limit_utc
        else None
    )
    insight = {
        "id": "H2-STILL-AIR-LINE-BINDS",
        "edge_case": "H2 (R02 hazard-interdependency 8)",
        "label": "synthetic units on real AGS weather",
        "feeder_id": line["feeder_id"],
        "transformer_id": line["transformer_id"],
        "conductor": line["conductor"]["name"],
        "rating_basis": case(rating),
        "still_air": case(still),
        "line_leads_transformer_h": cm.r(lead_h, 1) if lead_h is not None else None,
        "seeded_insight_holds": rating.binding == "transformer" and still.binding == "line",
        "advice": {
            "action": "transfer load off the FDR-AIK-2219 trunk before the afternoon peak",
            "tier": Tier.T2.value,
            "why": "in still air the conductor reaches its thermal limit before the transformer hot spot "
            "reaches warning; transformer cooling alone does not relieve the binding limit",
        },
        "protected_load_check": {
            "assets": sorted(str(s["asset_id"]) for s in table if s["protected_load"]),
            "rule": "units serving PS-17 and HSP-AIK-TALLOWBRANCH stay out of shed blocks",
            "shed_execution_tier": Tier.T4.value,
            "shed_execution": "refer to the system operator",
        },
    }
    trig_out = {
        "rule_id": "rule.heat.station_mean_tmax_p95_2days",
        "threshold_c": cm.r(trig.threshold_c, 2),
        "calibration_summer_days": trig.calibration_days,
        "fire_days_local": [d.isoformat() for d in trig.fire_days],
        "fired_in_window": bool(fires),
        "fire_utc": cm.iso(fire_utc) if fire_utc else None,
        "forecast_note": "observed Tmax stands in for a day-ahead forecast (perfect-forecast proxy)",
    }
    s_ = cm.sink(SCENARIO, *WINDOW)
    if fire_utc is not None:
        s_.add(
            "WeatherAlert",
            epoch(fire_utc),
            {
                "alert_id": f"HEAT-SYN-AIKRCH-{fires[0]:%m%d}",
                "product": "advisory",
                "event_name": "Heat Advisory",
                "severity": "elevated",
                "area_fips": ALERT_FIPS,
                "effective_utc": fire_utc,
                "expires_utc": WINDOW[1],
                "headline": "Heat trigger (synthetic alert from footprint station Tmax)",
            },
            key=f"heat-{fires[0]:%Y%m%d}",
            source="nws-alerts",
            region="SC",
        )
    header = cm.write_feed(
        out,
        SCENARIO,
        "weather",
        s_.by_feed.get("weather", []),
        *WINDOW,
        calibration_source="ASOS AGS/CAE/CHS/GSP/SAV; trigger threshold from summer 2023",
        note="Generated by `uv run python -m sgw.generator.scenarios generate heat`. Alerts are synthetic.",
    )
    summary = {
        "scenario": SCENARIO,
        "window_utc": [cm.iso(WINDOW[0]), cm.iso(WINDOW[1])],
        "trigger": trig_out,
        "insight": insight,
        "units": len(table),
        "units_in_warning_or_worse": sum(1 for s in table if s["alarm"] in ("warning", "emergency")),
        "weather_body_sha256": header.body_sha256,
    }
    cm.write_json(out / "insight.json", summary)
    cm.write_manifest(
        out, SCENARIO, ["weather.jsonl", "hot_spot.csv", "insight.json"], [AGS_HOURLY, STATIONS_DAILY]
    )
    return summary


def window_dates() -> tuple[date, date]:
    return WINDOW[0].astimezone(hs.EASTERN).date(), WINDOW[1].astimezone(hs.EASTERN).date()
