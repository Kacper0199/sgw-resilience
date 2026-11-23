"""Read side of the hazard library: the WP-22 second-tier scenarios as read-only views with their own
as-of dates, independent of the replay clock.

- Heat wave, July 2024 (`data/fixtures/heat/`): station-mean daily maximum temperature from real ASOS daily
  extracts against the trigger threshold of `insight.json` (calibrated on summer 2023, so 2024 is out of
  sample); transformer hot spots from `hot_spot.csv` and the still-air line check from `insight.json`, both
  synthetic units on real Augusta weather.
- Table Rock fire weather, March 2025 (`data/fixtures/tablerock/`): hourly Fosberg index and humidity at GSP
  computed from the real ASOS hourly extract with the WP-22 index and trigger code; Red Flag episodes, the
  protocol and the real NIFC fire anchors from `trigger.json`; the synthetic circuit ranking from
  `circuit_ranking.csv`.

Signers of each recommended step are SGW policy, assumed (P-SX3-01): a T2 operating step on one feeder or a
circuit list mirrors `stage_crews_small` (Operations signs); a T3 de-energisation mirrors `publish_global_etr`
(Command and Operations); T4 steps are referred outside SGW and have no SGW signer.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path
from typing import Any

from sgw.contracts.api_models import (
    CircuitRisk,
    FireAnchor,
    FireEpisode,
    FireWeatherHour,
    HazardAction,
    HazardLibraryHeat,
    HazardLibraryWildfire,
    HazardSource,
    HeatDay,
    HeatLineCheck,
    HeatUnit,
    Provenance,
)
from sgw.contracts.vocab import ApprovalFunction, NumberLabel, Tier
from sgw.generator.scenarios import weather
from sgw.models.heat import hotspot
from sgw.models.wildfire import trigger as wf_trigger
from sgw.reference.load import county_features

REPO = Path(__file__).resolve().parents[4]
HEAT_DIR = REPO / "data" / "fixtures" / "heat"
FIRE_DIR = REPO / "data" / "fixtures" / "tablerock"
HEAT_MONTH = (date(2024, 7, 1), date(2024, 7, 31))
TOP_CIRCUITS = 10
FIRE_STATION = "GSP"
OPERATIONS = [ApprovalFunction.OPERATIONS]
SIGNERS_BY_TIER: dict[Tier, list[ApprovalFunction]] = {
    Tier.T2: OPERATIONS,
    Tier.T3: [ApprovalFunction.COMMAND, ApprovalFunction.OPERATIONS],
    Tier.T4: [],
}


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _header(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        first: dict[str, Any] = json.loads(fh.readline())
    return first


@cache
def _county_names() -> dict[str, str]:
    return {str(f["properties"]["fips"]): str(f["properties"]["name"]) for f in county_features()}


def _county(fips: str) -> str:
    return _county_names().get(fips, fips)


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


@cache
def heat() -> HazardLibraryHeat:
    insight_doc = _json(HEAT_DIR / "insight.json")
    insight = insight_doc["insight"]
    trig = insight_doc["trigger"]
    threshold = float(trig["threshold_c"])
    stations = [str(s) for s in hotspot.value("trigger", "stations")]
    daily = weather.load_daily(HEAT_DIR / "asos_5stn_daily.csv")
    means = hotspot.station_mean_tmax([(d.station, d.day, d.tmax_c) for d in daily], stations)
    first, last = HEAT_MONTH
    days = [
        HeatDay(day=d.isoformat(), tmax_c=round(v, 2), hot=v >= threshold)
        for d, v in means.items()
        if first <= d <= last
    ]
    with (HEAT_DIR / "hot_spot.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    units = sorted(
        (
            HeatUnit(
                asset_id=r["asset_id"],
                site=r["site"],
                protected_load=r["protected_load"] == "true",
                peak_hot_spot_c=float(r["theta_h_peak_c"]),
                peak_utc=_utc(r["peak_utc"]),
                hours_ge_110c=float(r["hours_ge_110c"]),
                hours_ge_120c=float(r["hours_ge_120c"]),
                aging_equiv_days=float(r["aging_equiv_days"]),
                alarm=r["alarm"],  # type: ignore[arg-type]
                first_warning_utc=_utc(r["first_warning_utc"]) if r["first_warning_utc"] else None,
            )
            for r in rows
        ),
        key=lambda u: -u.peak_hot_spot_c,
    )
    still, rated = insight["still_air"], insight["rating_basis"]
    line = HeatLineCheck(
        feeder_id=insight["feeder_id"],
        conductor=insight["conductor"],
        still_air_peak_loading_pct=float(still["peak_line_loading_pct"]),
        rating_wind_peak_loading_pct=float(rated["peak_line_loading_pct"]),
        line_limit_utc=_utc(still["line_limit_utc"]) if still["line_limit_utc"] else None,
        transformer_warning_utc=_utc(still["transformer_warning_utc"])
        if still["transformer_warning_utc"]
        else None,
        line_leads_transformer_h=float(insight["line_leads_transformer_h"]),
    )
    advice, shed = insight["advice"], insight["protected_load_check"]
    shed_tier = Tier(shed["shed_execution_tier"])
    actions = [
        HazardAction(
            action_id="heat.transfer_load",
            text=_sentence(advice["action"]),
            tier=Tier(advice["tier"]),
            signers=SIGNERS_BY_TIER[Tier(advice["tier"])],
            applies_to=insight["feeder_id"],
            recommended=True,
            why=_sentence(advice["why"]),
        ),
        HazardAction(
            action_id="heat.protect_critical_load",
            text="Keep units serving PS-17 and Tallowbranch hospital out of any shed block; refer shedding to"
            " the system operator",
            tier=shed_tier,
            signers=SIGNERS_BY_TIER[shed_tier],
            applies_to=", ".join(shed["assets"]),
            recommended=True,
            why=_sentence(shed["rule"]),
        ),
    ]
    window = insight_doc["window_utc"]
    fired = _utc(trig["fire_utc"])
    return HazardLibraryHeat(
        title="Heat wave, July 2024",
        window_start_utc=_utc(window[0]),
        window_end_utc=_utc(window[1]),
        as_of=fired,
        trigger_rule_id=trig["rule_id"],
        threshold_c=threshold,
        trigger_fired_utc=fired,
        stations=stations,
        days=days,
        units=units,
        line=line,
        actions=actions,
        sources=[
            HazardSource(
                what=f"Daily maximum temperature, {len(stations)} ASOS stations",
                source=_rel(HEAT_DIR / "asos_5stn_daily.csv"),
                origin="real",
                detail="Iowa Environmental Mesonet ASOS archive (NWS/FAA METAR); threshold from summer 2023",
            ),
            HazardSource(
                what="Hourly weather at Augusta (AGS), the input to the unit models",
                source=_rel(HEAT_DIR / "asos_ags_hourly_heatwave.csv"),
                origin="real",
                detail="Iowa Environmental Mesonet ASOS archive (NWS/FAA METAR)",
            ),
            HazardSource(
                what="Transformer hot spots",
                source=_rel(HEAT_DIR / "hot_spot.csv"),
                origin="synthetic",
                detail=insight["label"],
            ),
            HazardSource(
                what="Line check and recommended action",
                source=_rel(HEAT_DIR / "insight.json"),
                origin="synthetic",
                detail=f"{insight['id']}; {trig['forecast_note']}",
            ),
        ],
        provenance=Provenance(
            source=_rel(HEAT_DIR),
            model_id="sgw.models.heat.hotspot",
            rule_id=trig["rule_id"],
            as_of=fired,
            label=NumberLabel.S,
            detail=_json(HEAT_DIR / "manifest.json")["label"],
        ),
    )


def fire_hours(start: datetime, end: datetime) -> list[FireWeatherHour]:
    obs = [o for o in weather.load_hourly(FIRE_DIR / "asos_gsp_hourly.csv") if start <= o.t < end]
    result = wf_trigger.evaluate(obs, {})
    by_t = {o.t: o for o in obs}
    return [
        FireWeatherHour(
            t_utc=h.t,
            ffwi=round(h.ffwi, 1),
            rh_pct=round(h.rh_pct, 1),
            wind_ms=round(by_t[h.t].wind_ms, 2),
            red_flag=h.ffwi_branch,
        )
        for h in result.hours
    ]


@cache
def wildfire() -> HazardLibraryWildfire:
    trig = _json(FIRE_DIR / "trigger.json")
    window = _header(FIRE_DIR / "weather.jsonl")["scenario_window"]
    start, end = _utc(window["start_utc"]), _utc(window["end_utc"])
    rule = wf_trigger.TriggerRule.default()
    episodes = [
        FireEpisode(
            start_utc=_utc(e["start_utc"]),
            end_utc=_utc(e["end_utc"]),
            hours=int(e["active_hours"]),
            ffwi_max=float(e["ffwi_max"]),
            rh_min_pct=float(e["rh_min_pct"]),
        )
        for e in trig["episodes"]
    ]
    anchors = trig["ignition_anchors"]
    fires = [
        FireAnchor(
            name=f["name"],
            acres=int(f["acres"]),
            county_fips=f["county_fips"],
            county=_county(f["county_fips"]),
            discovered_utc=_utc(f["discovered_utc"]),
        )
        for f in anchors["fires"]
    ]
    with (FIRE_DIR / "circuit_ranking.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    circuits = [
        CircuitRisk(
            rank=int(r["rank"]),
            feeder_id=r["feeder_id"],
            county_fips=r["fips"],
            county=_county(r["fips"]),
            customers=int(r["customers"]),
            overhead_km=float(r["overhead_km"]),
            p_ignition_window=float(r["p_ignition_window"]),
            ratio_to_average_window=float(r["ratio_to_average_window"]),
        )
        for r in sorted(rows, key=lambda r: int(r["rank"]))[:TOP_CIRCUITS]
    ]
    actions = sorted(
        (
            HazardAction(
                action_id=f"wildfire.{p['action']}",
                text=p["text"],
                tier=Tier(p["tier"]),
                signers=SIGNERS_BY_TIER[Tier(p["tier"])],
                applies_to=p["applies_to"],
                recommended=bool(p["recommended"]),
            )
            for p in trig["protocol"]
        ),
        key=lambda a: not a.recommended,
    )
    first_fire = _utc(trig["first_fire_utc"])
    ranking = trig["ranking"]
    return HazardLibraryWildfire(
        title="Wildfire weather, March 2025",
        window_start_utc=start,
        window_end_utc=end,
        as_of=first_fire,
        trigger_rule_id=rule.rule_id,
        ffwi_min=rule.ffwi_min,
        rh_max_pct=rule.rh_max_pct,
        min_hours=rule.min_hours,
        station=FIRE_STATION,
        hours=fire_hours(start, end),
        episodes=episodes,
        fires=fires,
        kbdi_max=max(float(v) for v in trig["kbdi_window"].values()),
        kbdi_min_trigger=rule.kbdi_min,
        circuits=circuits,
        circuits_total=int(ranking["circuits"]),
        expected_ignitions_all=float(ranking["expected_ignitions_all_circuits"]),
        actions=actions,
        sources=[
            HazardSource(
                what="Hourly weather at Greenville-Spartanburg (GSP)",
                source=_rel(FIRE_DIR / "asos_gsp_hourly.csv"),
                origin="real",
                detail="Iowa Environmental Mesonet ASOS archive (NWS/FAA METAR); fire index computed by SGW",
            ),
            HazardSource(
                what="Table Rock fires",
                source=_rel(FIRE_DIR / "trigger.json"),
                origin="real",
                detail=anchors["source"],
            ),
            HazardSource(
                what="Circuit ignition ranking",
                source=_rel(FIRE_DIR / "circuit_ranking.csv"),
                origin="synthetic",
                detail=trig["label"],
            ),
            HazardSource(
                what="Red Flag protocol",
                source=_rel(FIRE_DIR / "trigger.json"),
                origin="synthetic",
                detail=ranking["drought_signal"],
            ),
        ],
        provenance=Provenance(
            source=_rel(FIRE_DIR),
            model_id="sgw.models.wildfire.ranking",
            rule_id=rule.rule_id,
            as_of=first_fire,
            label=NumberLabel.S,
            detail=_json(FIRE_DIR / "manifest.json")["label"],
        ),
    )
