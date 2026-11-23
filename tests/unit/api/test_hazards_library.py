"""Hazard library over HTTP (router alone, session dependency overridden) and against the committed
Fixtures: every value is traced to the file it is read from, real ASOS inputs are labelled real and the
SGW-built outputs synthetic, and the views do not depend on the replay clock."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from sgw.api.deps import current_user
from sgw.api.readmodels import hazards_library as rm
from sgw.api.routers import hazards_library as router_mod
from sgw.api.sessions import AuthUser
from sgw.contracts.api_models import HazardLibraryHeat, HazardLibraryWildfire, contract_routes
from sgw.contracts.vocab import ApprovalFunction, Domain, NumberLabel, Tier

REPO = Path(__file__).resolve().parents[3]
HEAT = REPO / "data" / "fixtures" / "heat"
FIRE = REPO / "data" / "fixtures" / "tablerock"
HEAT_PATH = "/api/hazards/library/heat"
FIRE_PATH = "/api/hazards/library/wildfire"
EXEC = AuthUser(
    user_id="exec_01",
    display_name="Executive",
    function=ApprovalFunction.EXECUTIVE,
    roles=("executive",),
    regions=("SC", "GA"),
    domains=(Domain.ELECTRIC, Domain.WATER),
    step_up_at=None,
    session_hash="0" * 64,
    demo_switch=False,
)


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router_mod.router)
    app.dependency_overrides[current_user] = lambda: EXEC
    return TestClient(app)


def test_routes_are_in_the_contract() -> None:
    routes = contract_routes()
    assert ("GET", HEAT_PATH) in routes
    assert ("GET", FIRE_PATH) in routes


def test_both_views_need_a_session() -> None:
    for route in router_mod.router.routes:
        assert isinstance(route, APIRoute)
        calls = {d.call for d in route.dependant.dependencies}
        assert current_user in calls, route.path


def test_heat_over_http_carries_provenance_and_etag(client: TestClient) -> None:
    res = client.get(HEAT_PATH)
    assert res.status_code == 200
    view = HazardLibraryHeat.model_validate(res.json())
    header = res.headers["x-sgw-provenance"]
    assert "source=data/fixtures/heat" in header
    assert "as_of=2024-07-15T04:00:00Z" in header
    assert f"label={NumberLabel.S.value}" in header
    assert view.provenance.label is NumberLabel.S
    again = client.get(HEAT_PATH, headers={"If-None-Match": res.headers["etag"]})
    assert again.status_code == 304


def test_heat_days_are_the_station_mean_of_the_real_daily_extract() -> None:
    view = rm.heat()
    stations = set(view.stations)
    by_day: dict[str, dict[str, float]] = defaultdict(dict)
    with (HEAT / "asos_5stn_daily.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["date_local"].startswith("2024-07"):
                by_day[r["date_local"]][r["station"]] = float(r["tmax_c"])
    expected = {d: math.fsum(v.values()) / len(v) for d, v in by_day.items() if stations <= set(v)}
    assert [d.day for d in view.days] == sorted(expected)
    for d in view.days:
        assert d.tmax_c == pytest.approx(expected[d.day], abs=0.01)
        assert d.hot is (expected[d.day] >= view.threshold_c)
    trig = _json(HEAT / "insight.json")["trigger"]
    assert view.threshold_c == trig["threshold_c"]
    assert view.trigger_fired_utc == _utc(trig["fire_utc"])
    assert view.as_of == view.trigger_fired_utc
    hot = [d.day for d in view.days if d.hot]
    assert "2024-07-14" in hot and "2024-07-15" in hot


def test_heat_units_and_line_check_match_the_fixture() -> None:
    view = rm.heat()
    with (HEAT / "hot_spot.csv").open(newline="", encoding="utf-8") as fh:
        rows = {r["asset_id"]: r for r in csv.DictReader(fh)}
    assert {u.asset_id for u in view.units} == set(rows)
    peaks = [u.peak_hot_spot_c for u in view.units]
    assert peaks == sorted(peaks, reverse=True)
    for u in view.units:
        r = rows[u.asset_id]
        assert u.peak_hot_spot_c == float(r["theta_h_peak_c"])
        assert u.hours_ge_120c == float(r["hours_ge_120c"])
        assert u.alarm == r["alarm"]
        assert u.protected_load is (r["protected_load"] == "true")
    insight = _json(HEAT / "insight.json")["insight"]
    assert (
        sum(u.alarm in {"warning", "emergency"} for u in view.units)
        == _json(HEAT / "insight.json")["units_in_warning_or_worse"]
    )
    assert view.line.feeder_id == insight["feeder_id"] == "FDR-AIK-2219"
    assert view.line.still_air_peak_loading_pct == insight["still_air"]["peak_line_loading_pct"]
    assert view.line.rating_wind_peak_loading_pct == insight["rating_basis"]["peak_line_loading_pct"]
    assert view.line.line_leads_transformer_h == insight["line_leads_transformer_h"]


def test_heat_action_has_tier_and_signers() -> None:
    first, second = rm.heat().actions
    assert first.recommended and first.tier is Tier.T2
    assert first.signers == [ApprovalFunction.OPERATIONS]
    assert "FDR-AIK-2219" in first.text
    assert second.tier is Tier.T4 and second.signers == []


def test_heat_sources_label_real_and_synthetic() -> None:
    origins = {s.source: s.origin for s in rm.heat().sources}
    assert origins["data/fixtures/heat/asos_5stn_daily.csv"] == "real"
    assert origins["data/fixtures/heat/asos_ags_hourly_heatwave.csv"] == "real"
    assert origins["data/fixtures/heat/hot_spot.csv"] == "synthetic"
    assert origins["data/fixtures/heat/insight.json"] == "synthetic"
    assert all((REPO / s).is_file() for s in origins)


def test_wildfire_over_http_carries_provenance(client: TestClient) -> None:
    res = client.get(FIRE_PATH)
    assert res.status_code == 200
    view = HazardLibraryWildfire.model_validate(res.json())
    header = res.headers["x-sgw-provenance"]
    assert "source=data/fixtures/tablerock" in header
    assert "as_of=2025-03-19T17:00:00Z" in header
    assert view.provenance.model_id == "sgw.models.wildfire.ranking"


def test_wildfire_hours_reproduce_the_fixture_episodes() -> None:
    view = rm.wildfire()
    trig = _json(FIRE / "trigger.json")
    assert all(view.window_start_utc <= h.t_utc < view.window_end_utc for h in view.hours)
    flagged = [h for h in view.hours if h.red_flag]
    assert len(flagged) == sum(e["active_hours"] for e in trig["episodes"])
    for e in trig["episodes"]:
        start, end = _utc(e["start_utc"]), _utc(e["end_utc"])
        inside = [h for h in flagged if start <= h.t_utc <= end]
        assert len(inside) == e["active_hours"]
        assert max(h.ffwi for h in inside) == pytest.approx(e["ffwi_max"], abs=0.1)
        assert min(h.rh_pct for h in inside) == pytest.approx(e["rh_min_pct"], abs=0.1)
    assert all(h.ffwi >= view.ffwi_min and h.rh_pct <= view.rh_max_pct for h in flagged)
    assert view.as_of == _utc(trig["first_fire_utc"])


def test_wildfire_circuits_fires_and_protocol_match_the_fixture() -> None:
    view = rm.wildfire()
    trig = _json(FIRE / "trigger.json")
    with (FIRE / "circuit_ranking.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert view.circuits_total == len(rows) == trig["ranking"]["circuits"]
    assert [c.feeder_id for c in view.circuits] == [r["feeder_id"] for r in rows[:10]]
    assert view.circuits[0].p_ignition_window == float(rows[0]["p_ignition_window"])
    assert view.circuits[0].county == "Pickens"
    assert [(f.name, f.acres, f.county) for f in view.fires] == [
        ("Table Rock", 13845, "Pickens"),
        ("Table Rock Complex", 15973, "Greenville"),
    ]
    assert view.kbdi_max == max(trig["kbdi_window"].values())
    assert view.kbdi_max < view.kbdi_min_trigger
    assert view.expected_ignitions_all == trig["ranking"]["expected_ignitions_all_circuits"]
    first = view.actions[0]
    assert first.recommended and first.tier is Tier.T2 and first.signers == [ApprovalFunction.OPERATIONS]
    last = view.actions[-1]
    assert not last.recommended and last.tier is Tier.T3
    assert {a.action_id for a in view.actions} == {f"wildfire.{p['action']}" for p in trig["protocol"]}


def test_wildfire_sources_label_real_and_synthetic() -> None:
    sources = rm.wildfire().sources
    real = {s.what for s in sources if s.origin == "real"}
    synthetic = {s.what for s in sources if s.origin == "synthetic"}
    assert any("GSP" in w for w in real)
    assert "Table Rock fires" in real
    assert "Circuit ignition ranking" in synthetic
    assert all((REPO / s.source).is_file() for s in sources)


def test_views_ignore_the_replay_clock() -> None:
    assert rm.heat().as_of.year == 2024 and rm.heat().as_of.month == 7
    assert rm.wildfire().as_of.year == 2025 and rm.wildfire().as_of.month == 3
