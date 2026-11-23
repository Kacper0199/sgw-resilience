"""Over HTTP with the real app lifespan on a scratch database seeded by `seed_demo` exactly as
`sgw seed --demo` does (users, reference rows, Helene replay, PS-17 queue, ETR publication, the WP-11 risk
picture of every advisory at its issue time, the WP-16 crew plan for advisory N with smaller SAA sizes), run
twice to check it is idempotent. Covers auth, response shape and at least one value per route traced to its
engine or artefact; nothing published after the scenario clock is visible."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.unit.api.clock_testkit import pin_clock

from sgw.api.app import create_app
from sgw.api.deps import current_user
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk
from sgw.contracts.api_models import (
    CountyForecast,
    CountyOutagesNow,
    CrewItem,
    CrewPlanDocument,
    DamageQueue,
    ForecastResponse,
    HazardAdvisoryDetail,
    OutageItem,
    PlanDiff,
    RiskResponse,
    WhatIfGrid,
)
from sgw.contracts.vocab import ApprovalFunction, Domain

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "data" / "fixtures" / "helene"
SMALL_SAA = {"n_out": 400, "replications": 3, "n_evpi": 10, "n_cvar": 200}
NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
T_BEFORE = datetime(2024, 9, 24, 0, 0, tzinfo=UTC)
T_N = datetime(2024, 9, 26, 10, 0, tzinfo=UTC)
T_N1 = datetime(2024, 9, 26, 16, 0, tzinfo=UTC)
T_OUT = datetime(2024, 9, 27, 6, 0, tzinfo=UTC)
T_END = datetime(2024, 10, 6, 12, 0, tzinfo=UTC)
READER = AuthUser(
    user_id="audit_01",
    display_name="Auditor",
    function=ApprovalFunction.AUDIT,
    roles=("auditor",),
    regions=("SC", "GA"),
    domains=(Domain.ELECTRIC, Domain.WATER),
    step_up_at=None,
    session_hash="0" * 64,
    demo_switch=False,
)
PATHS = (
    "/api/risk",
    "/api/forecasts?target=outages&entity=45003",
    "/api/forecasts/outages/counties",
    "/api/forecasts/outages/plan-diff",
    "/api/outages",
    "/api/outages/counties",
    "/api/crews",
    "/api/crews/plan",
    "/api/damage/queue",
    "/api/damage/thumbs/ladi-v2-test-0016",
    "/api/models/outage_loso/evaluation",
    "/api/hazard/advisories",
    "/api/hazard/advisories/N",
    "/api/whatif",
)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    from sgw.approval.demo_seed import seed_demo
    from sgw.models.optimise.job import JOB_KIND

    with tk.scratch_database("sgw_beui2a_t") as url:
        first = seed_demo(url, "beui2a-scratch-only", crew_plan_opts=SMALL_SAA)
        with psycopg.connect(url) as conn:
            counts = conn.execute(
                "SELECT kind, count(*) FROM snapshot GROUP BY kind ORDER BY kind"
            ).fetchall()
            jobs = conn.execute("SELECT count(*) FROM job WHERE kind = %s", (JOB_KIND,)).fetchone()
        again = seed_demo(url, "beui2a-scratch-only", crew_plan_opts=SMALL_SAA)
        with psycopg.connect(url) as conn:
            assert (
                conn.execute("SELECT kind, count(*) FROM snapshot GROUP BY kind ORDER BY kind").fetchall()
                == counts
            )
            assert conn.execute("SELECT count(*) FROM job WHERE kind = %s", (JOB_KIND,)).fetchone() == jobs
        assert len(first.risk_snapshots) == 12 and again.risk_snapshots == first.risk_snapshots
        assert first.crew_plan is not None and again.crew_plan == first.crew_plan
        yield url


def _client(db_url: str, *, signed_in: bool = True) -> TestClient:
    app = create_app(ApiSettings(database_url=db_url, demo_mode=True))
    if signed_in:
        app.dependency_overrides[current_user] = lambda: READER
    return TestClient(app)


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    with _client(db_url) as c:
        yield c


def at(client: TestClient, when: datetime) -> TestClient:
    """Stop the scenario clock at `when`, in the control row (the broadcaster re-reads it) and in-process."""
    pin_clock(client, when)
    return client


def _fixture_events(name: str, kind: str) -> list[dict[str, Any]]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [e for e in (json.loads(x) for x in lines if x.strip()) if e.get("type") == kind]


def test_every_route_needs_a_session(db_url: str) -> None:
    with _client(db_url, signed_in=False) as anon:
        for path in PATHS:
            r = anon.get(path)
            assert r.status_code == 401, path
            assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_risk_is_the_snapshot_in_force_with_engine_values(client: TestClient) -> None:
    from sgw.models.outage.forecast import advisory_risk

    body = RiskResponse.model_validate(at(client, T_N).get("/api/risk").json())
    assert body.advisory_label == "N" and len(body.items) == 123
    engine = advisory_risk("helene", "N").counties.set_index("fips")
    aiken = next(i for i in body.items if i.entity_id == "45003")
    assert aiken.p_ppm == int(engine.loc["45003", "p_ppm"])
    assert aiken.expected_impact == int(engine.loc["45003", "mean_out"])
    assert aiken.band.value == engine.loc["45003", "band"]
    assert aiken.drivers and all(isinstance(d, str) for d in aiken.drivers)
    assert body.provenance is not None and body.provenance.model_id == "a2-excl-helene"
    assert body.provenance.source == f"snapshot:{body.snapshot_id}" and body.provenance.as_of == body.as_of
    later = RiskResponse.model_validate(at(client, T_N1).get("/api/risk").json())
    assert later.advisory_label == "N+1"
    back = RiskResponse.model_validate(client.get("/api/risk?as_of=2024-09-26T10:00:00Z").json())
    assert back.advisory_label == "N"


def test_risk_never_looks_ahead_and_caps_ranked_assets(client: TestClient) -> None:
    future = at(client, T_N).get("/api/risk?as_of=2024-09-30T00:00:00Z").json()
    assert future["advisory_label"] == "N"
    assets = at(client, T_N1).get("/api/risk?level=asset").json()["items"]
    assert len(assets) == 25 and {a["level"] for a in assets} == {"asset"}
    impacts = [a["expected_impact"] for a in assets]
    assert impacts == sorted(impacts, reverse=True)
    none = at(client, T_BEFORE).get("/api/risk")
    assert none.status_code == 404 and none.json()["error"]["code"] == "RISK_NOT_PUBLISHED"
    assert client.get("/api/risk?level=h4").status_code == 422
    assert client.get("/api/risk?as_of=yesterday").status_code == 422


def test_severity_follows_the_band(client: TestClient) -> None:
    from sgw.models.outage.read import BAND_SEVERITY

    items = at(client, T_N1).get("/api/risk").json()["items"]
    assert all(i["severity"] == BAND_SEVERITY[i["band"]].value for i in items)


def test_outage_forecast_series_grows_with_each_advisory(client: TestClient) -> None:
    from sgw.models.outage.forecast import advisory_risk

    one = ForecastResponse.model_validate(
        at(client, T_N).get("/api/forecasts?target=outages&entity=45003").json()
    )
    two = ForecastResponse.model_validate(
        at(client, T_N1).get("/api/forecasts?target=outages&entity=45003").json()
    )
    assert len(one.series) == 8 and len(two.series) == 9
    engine = advisory_risk("helene", "N+1").counties.set_index("fips").loc["45003"]
    last = two.series[-1]
    assert (last.p10, last.p50, last.p90) == (
        float(engine["q0100_out"]),
        float(engine["q0500_out"]),
        float(engine["q0900_out"]),
    )
    assert two.provenance is not None and two.provenance.model_id == "a2-excl-helene"
    assert client.get("/api/forecasts?target=pressure&entity=45003").status_code == 422
    assert client.get("/api/forecasts?target=outages").status_code == 422
    miss = client.get("/api/forecasts?target=outages&entity=99999")
    assert miss.status_code == 404 and miss.json()["error"]["code"] == "FORECAST_NOT_FOUND"


def test_etr_forecast_is_hours_from_issue(client: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        row = conn.execute(
            "SELECT output FROM snapshot WHERE kind = 'etr' ORDER BY as_of DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    glob = next(e for e in row[0] if e["region_id"] == "GLOBAL")
    body = ForecastResponse.model_validate(
        at(client, T_END).get("/api/forecasts?target=etr&entity=GLOBAL").json()
    )
    assert body.series[-1].p50 == pytest.approx(glob["hours_from_as_of"]["p50"], abs=0.05)
    assert body.unit is not None and "hours" in body.unit


def test_county_fans_and_actions_of_one_advisory(client: TestClient) -> None:
    from sgw.models.outage.forecast import advisory_risk

    body = CountyForecast.model_validate(
        at(client, T_N1).get("/api/forecasts/outages/counties?advisory=N").json()
    )
    engine = advisory_risk("helene", "N")
    fans = engine.counties.set_index("fips")
    assert body.advisory_label == "N" and len(body.counties) == 123
    aiken = next(c for c in body.counties if c.fips == "45003")
    assert aiken.name == fans.loc["45003", "name"] and aiken.customers == int(fans.loc["45003", "customers"])
    assert (aiken.q0500, aiken.mean) == (
        int(fans.loc["45003", "q0500_out"]),
        int(fans.loc["45003", "mean_out"]),
    )
    assert [a.share_ppm for a in body.actions] == [a.share_ppm for a in engine.actions]
    assert any(a.label != a.action_id for a in body.actions)
    assert body.members == engine.meta["members"]
    early = at(client, T_N).get("/api/forecasts/outages/counties?advisory=N%2B1")
    assert early.status_code == 404 and early.json()["error"]["code"] == "FORECAST_NOT_PUBLISHED"
    assert client.get("/api/forecasts/outages/counties?advisory=../x").status_code == 422


def test_plan_diff_from_n_to_n_plus_1(client: TestClient) -> None:
    from sgw.models.outage.forecast import advisory_risk
    from sgw.models.outage.plan_diff import plan_diff

    body = PlanDiff.model_validate(at(client, T_N1).get("/api/forecasts/outages/plan-diff?to=N%2B1").json())
    engine = plan_diff(advisory_risk("helene", "N"), advisory_risk("helene", "N+1"))
    assert (body.from_advisory, body.to_advisory) == ("N", "N+1")
    assert list(body.footprint_mean_out) == engine["footprint_mean_out"]
    assert [list(a.share_ppm) for a in body.actions] == [a["share_ppm"] for a in engine["actions"]]
    assert body.act_now_policy_key == "policy_no_regret_act_now_ppm"
    assert body.provenance.rule_id == "policy_no_regret_act_now_ppm"
    assert len(body.assets) <= 25
    assert at(client, T_N).get("/api/forecasts/outages/plan-diff?to=N%2B1").status_code == 404
    assert client.get("/api/forecasts/outages/plan-diff").json()["to_advisory"] == "N"


def test_open_outages_follow_the_oms_events(client: TestClient) -> None:
    body = [OutageItem.model_validate(o) for o in at(client, T_OUT).get("/api/outages").json()]
    known = [
        e
        for e in _fixture_events("oms.jsonl", "OutageEvent")
        if e["scenario_known_at"] <= "2024-09-27T06:00:00Z"
    ]
    latest: dict[str, dict[str, Any]] = {}
    first: dict[str, str] = {}
    for e in sorted(known, key=lambda e: e["scenario_known_at"]):
        latest[e["payload"]["outage_id"]] = e
        first.setdefault(e["payload"]["outage_id"], e["event_time"])
    expected = {k for k, e in latest.items() if e["payload"]["status"] != "restored"}
    assert expected and {o.outage_id for o in body} == expected
    one = next(o for o in body if o.outage_id == sorted(expected)[0])
    assert one.customers_out == latest[one.outage_id]["payload"]["customers_out"]
    assert one.started_at == datetime.fromisoformat(first[one.outage_id].replace("Z", "+00:00"))
    assert one.provenance is not None and one.provenance.source == "oms"
    assert [o.customers_out for o in body] == sorted((o.customers_out for o in body), reverse=True)
    assert at(client, T_BEFORE).get("/api/outages").json() == []


def test_county_outages_now_are_the_briefing_feed_hour(client: TestClient) -> None:
    from sgw.reports.sources import replay_status

    lifted = datetime(2024, 9, 30, 12, 0, tzinfo=UTC)
    body = CountyOutagesNow.model_validate(at(client, lifted).get("/api/outages/counties").json())
    status = replay_status(lifted)
    assert body.as_of == status.as_of
    assert sum(c.customers_out for c in body.counties) == body.customers_out_now == status.customers_out_now
    by_fips = {c.fips: c.customers_out for c in body.counties}
    assert by_fips["45045"] == 4505
    assert "45003" not in by_fips
    assert all(n > 0 for n in by_fips.values())
    earlier = client.get("/api/outages/counties?as_of=2024-09-27T12:00:00Z").json()
    assert (
        earlier["customers_out_now"]
        == replay_status(datetime(2024, 9, 27, 12, 0, tzinfo=UTC)).customers_out_now
    )
    empty = CountyOutagesNow.model_validate(
        client.get("/api/outages/counties?as_of=2024-09-24T00:00:00Z").json()
    )
    assert empty.as_of is None and empty.counties == [] and empty.customers_out_now == 0


def test_crews_report_their_latest_status(client: TestClient) -> None:
    body = [CrewItem.model_validate(c) for c in at(client, T_N1).get("/api/crews").json()]
    known = [
        e
        for e in _fixture_events("fsm.jsonl", "CrewStatus")
        if e["scenario_known_at"] <= "2024-09-26T16:00:00Z"
    ]
    latest: dict[str, dict[str, Any]] = {}
    for e in sorted(known, key=lambda e: e["scenario_known_at"]):
        latest[e["payload"]["crew_id"]] = e
    assert {c.crew_id for c in body} == set(latest)
    crew = body[0]
    assert crew.status.value == latest[crew.crew_id]["payload"]["status"]
    assert crew.headcount == latest[crew.crew_id]["payload"]["headcount"]
    status = crew.status.value
    filtered = client.get(f"/api/crews?status={status}").json()
    assert filtered and {c["status"] for c in filtered} == {status}
    assert client.get("/api/crews?status=asleep").status_code == 422


def test_crew_plan_is_p50_beside_the_courses_of_action(client: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        row = conn.execute("SELECT snapshot_id, output FROM snapshot WHERE kind = 'crew_plan'").fetchone()
    assert row is not None
    sid, doc = row
    assert at(client, T_BEFORE).get("/api/crews/plan").status_code == 404
    r = at(client, T_N1).get("/api/crews/plan")
    assert r.status_code == 200, r.text
    body = CrewPlanDocument.model_validate(r.json())
    assert [p.plan_id for p in body.plans] == ["P50", "COA-A", "COA-B", "COA-C"]
    assert "EV" in {p["plan_id"] for p in doc["plans"]}
    assert body.vss.ev.value == doc["vss"]["ev"]["value"] and body.evpi.in_sample == doc["evpi"]["in_sample"]
    stored = {p["plan_id"]: p for p in doc["plans"]}
    for plan in body.plans[1:]:
        request = stored[plan.plan_id].get("resource_request")
        assert plan.resource_request_id == (request["MessageID"] if request else None)
    assert body.plans[1].envelope is not None and body.plans[1].envelope.bounds
    assert '"resource_request"' not in r.text and "cvar_check" not in r.text and "replications" not in r.text
    assert body.recommendation is None and body.provenance.source == f"snapshot:{sid}"
    assert client.get("/api/crews/plan?advisory=N%2B1").status_code == 404


def test_damage_queue_orders_photos_and_tiers_cases(client: TestClient) -> None:
    queue = json.loads((ROOT / "data/artefacts/cv/review_queue.json").read_text(encoding="utf-8"))
    body = DamageQueue.model_validate(client.get("/api/damage/queue?limit=12").json())
    ranks = [r.rank for r in body.rows]
    assert ranks == sorted(ranks) and body.total_photos == len(queue["rows"])
    case_photos = {p for c in body.cases for p in c.photo_ids}
    assert {r.image_id for r in body.rows} == {
        r["image_id"] for r in queue["rows"] if r["rank"] <= 12
    } | case_photos
    tiers = {c.case_id: c.tier for c in body.cases}
    assert tiers["FDR2207-WEAK-TRUNK"] == "structural" and tiers["D7-PRIORITY-CONFLICT"] == "slight"
    top = body.rows[0]
    assert (
        top.triage_score == queue["rows"][0]["triage_score"]
        and top.thumb_url == f"/api/damage/thumbs/{top.image_id}"
    )
    assert body.provenance.model_id == f"{queue['model_id']}@{queue['model_revision']}"
    assert client.get("/api/damage/queue?limit=0").status_code == 422


def test_thumbnails_only_for_queued_images(client: TestClient) -> None:
    r = client.get("/api/damage/thumbs/ladi-v2-test-0016")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content == (ROOT / "data/artefacts/cv/thumbs/test_0016.jpg").read_bytes()
    again = client.get("/api/damage/thumbs/ladi-v2-test-0016", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    for bad in ("ladi-v2-test-9999", "..%2F..%2Fmanifest.json", "test_0016.jpg", "%2E%2E"):
        assert client.get(f"/api/damage/thumbs/{bad}").status_code == 404, bad


def test_reads_carry_an_etag_and_answer_304(client: TestClient) -> None:
    first = at(client, T_N1).get("/api/risk")
    assert first.headers["cache-control"] == "private, no-cache" and first.headers["etag"]
    assert client.get("/api/risk", headers={"If-None-Match": first.headers["etag"]}).status_code == 304


def test_named_k17_reports_and_registered_models(client: TestClient) -> None:
    report = json.loads((ROOT / "evals/reports/outage_loso.json").read_text(encoding="utf-8"))
    body = client.get("/api/models/outage_loso/evaluation").json()
    assert body["metrics"] == report["metrics"] and body["command"] == report["command"]
    assert body["provenance"]["source"] == "evals/reports/outage_loso.json"
    for name in ("outage_loso_v2", "etr", "saa", "ladi_reference"):
        assert client.get(f"/api/models/{name}/evaluation").json()["name"] == name
    anomaly = client.get("/api/models/anomaly_a7_a8/evaluation").json()
    art = json.loads((ROOT / "data/artefacts/water_twin/anomaly_dev.json").read_text(encoding="utf-8"))
    recall = next(m for m in anomaly["metrics"] if m["metric"] == "anomaly.recall_raw")
    assert recall["value"] == art["results"]["dev_bench"]["metrics"]["recall"]
    assert recall["passed"] == (recall["value"] >= recall["threshold"])
    assert anomaly["caveats"] == art["limitations"]
    served = client.get("/api/models/a2-excl-helene/evaluation").json()
    assert served["serving"]["alias"] == "serving" and served["metrics"]
    for bad in ("nope", "..%2F..%2Fetc%2Fpasswd", "outage_loso.json"):
        assert client.get(f"/api/models/{bad}/evaluation").status_code == 404, bad


def test_read_helper_constants_match_the_engines() -> None:
    from sgw.models.optimise import coa, job
    from sgw.models.optimise import read as plan_read
    from sgw.models.outage import publisher
    from sgw.models.outage import read as outage_read
    from sgw.models.restoration import publish

    assert outage_read.OUTAGE_TARGET == publisher.FORECAST_TARGET
    assert outage_read.ETR_TARGET == publish.FORECAST_TARGET and outage_read.ETR_LABEL == publish.LABEL
    assert plan_read.SNAPSHOT_KIND == job.SNAPSHOT_KIND
    assert ("P50", *coa.COA_IDS) == plan_read.PLAN_ORDER


def test_hazard_advisories_issued_by_the_scenario_time(client: TestClient) -> None:
    ensemble = json.loads((FIXTURES / "ensemble.json").read_text(encoding="utf-8"))
    index = at(client, T_N).get("/api/hazard/advisories").json()
    assert [a["advisory_label"] for a in index] == ["N-7", "N-6", "N-5", "N-4", "N-3", "N-2", "N-1", "N"]
    assert index[-1]["next_advisory_utc"] == "2024-09-26T15:00:00Z"
    detail = HazardAdvisoryDetail.model_validate(client.get("/api/hazard/advisories/N").json())
    raw = next(a for a in ensemble["advisories"] if a["advisory_label"] == "N")
    assert [list(f) for f in detail.official_track] == [
        [float(v) for v in f] for f in raw["official"]["track"]
    ]
    i = ensemble["points"]["ids"].index("45003")
    assert detail.county_peak_gust_ms["45003"] == raw["official"]["peak_gust_ms"][i]
    assert len(detail.county_peak_gust_ms) == 123
    assert all(fix[0] <= "2024-09-26T09:00:00Z" for fix in detail.analysis_track)
    assert detail.cone.radius_nmi[:3] == [0.0, 26.0, 39.0] and len(detail.cone.lead_h) == len(
        detail.cone.radius_nmi
    )
    early = client.get("/api/hazard/advisories/N%2B1")
    assert early.status_code == 404 and early.json()["error"]["code"] == "ADVISORY_NOT_FOUND"
    assert client.get("/api/hazard/advisories/..%2F..%2Fetc").status_code == 404
    assert at(client, T_BEFORE).get("/api/hazard/advisories").json() == []


def test_whatif_is_the_precomputed_grid(client: TestClient) -> None:
    from sgw.models.whatif.grid import lookup

    body = WhatIfGrid.model_validate(client.get("/api/whatif").json())
    assert body.baseline.customer_hours == lookup({})["customer_hours"]
    named = {s.id: s for s in body.scenarios}
    assert set(named) == {"track_east", "wind_up", "aid_late"}
    assert named["wind_up"].customer_hours == lookup({"gust_scale": 1.1})["customer_hours"]
    assert named["track_east"].levers["track_shift_km"] == 40.0 and body.tier.value == "T0"
    assert body.provenance.source == "src/sgw/models/whatif/helene_grid.json"
