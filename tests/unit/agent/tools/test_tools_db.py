"""P2a parity over HTTP: each DB-backed executor returns the same rows and values as its REST page for the
same user and scenario time, on a scratch database seeded by `seed_demo` (as `sgw seed --demo` does)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from tests.unit.api.clock_testkit import pin_clock

from sgw.agent.tools.context import ToolContext
from sgw.agent.tools.outcome import EvidenceLedger
from sgw.agent.tools.reads import DbReads
from sgw.agent.tools.registry import run
from sgw.api.app import create_app
from sgw.api.deps import current_user
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk
from sgw.contracts.tools import InjectedContext
from sgw.contracts.vocab import ApprovalFunction, Classification, Domain, RunMode

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
SMALL_SAA = {"n_out": 400, "replications": 3, "n_evpi": 10, "n_cvar": 200}
T_N = datetime(2024, 9, 26, 10, 0, tzinfo=UTC)
T_OUT = datetime(2024, 9, 27, 6, 0, tzinfo=UTC)
T_END = datetime(2024, 10, 6, 12, 0, tzinfo=UTC)
COMMANDER = AuthUser(
    user_id="ic_01",
    display_name="Incident Commander",
    function=ApprovalFunction.COMMAND,
    roles=("incident_commander",),
    regions=("SC", "GA"),
    domains=(Domain.ELECTRIC, Domain.WATER),
    step_up_at=None,
    session_hash="0" * 64,
    demo_switch=False,
)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: P2a REST parity needs Postgres
    from sgw.approval.demo_seed import seed_demo

    with tk.scratch_database("sgw_r27tl_tools_t") as url:
        seed_demo(url, "r27tl-scratch-only", crew_plan_opts=SMALL_SAA)
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    app = create_app(ApiSettings(database_url=db_url, demo_mode=True))
    app.dependency_overrides[current_user] = lambda: COMMANDER
    with TestClient(app) as c:
        yield c


def at(client: TestClient, when: datetime) -> TestClient:
    pin_clock(client, when)
    return client


def ctx(db_url: str, when: datetime) -> ToolContext:
    injected = InjectedContext(
        as_of=when,
        user_id=COMMANDER.user_id,
        user_role=COMMANDER.function,
        region_ids=["SC-45003"],
        run_mode=RunMode.REPLAY,
        classification_ceiling=Classification.C1,
    )
    return ToolContext(injected=injected, reads=DbReads(db_url), ledger=EvidenceLedger())


async def test_risk_matches_the_risk_page(client: TestClient, db_url: str) -> None:
    page = at(client, T_N).get("/api/risk").json()
    by_id = {i["entity_id"]: i for i in page["items"]}
    out = await run("get_risk", {"level": "county"}, ctx(db_url, T_N))
    assert out.status == "ok" and len(out.new_items) == 10
    top = sorted(page["items"], key=lambda i: (-i["p_ppm"], -i["expected_impact"], i["entity_id"]))[:10]
    assert [i.entity_ids[0] for i in out.new_items] == [i["entity_id"] for i in top]
    for item in out.new_items:
        row = by_id[item.entity_ids[0]]
        assert (
            item.values["p"].value == row["p_ppm"]
            and item.values["expected_out"].value == row["expected_impact"]
        )
        assert item.band is not None and item.band.value == row["band"]
        assert page["snapshot_id"] in item.citation
    aiken = await run("get_risk", {"level": "county", "entity_ids": ["45003"]}, ctx(db_url, T_N))
    assert aiken.new_items[0].values["p"].value == by_id["45003"]["p_ppm"]
    assets = at(client, T_N).get("/api/risk?level=asset").json()["items"]
    got = await run(
        "get_risk", {"level": "asset", "entity_ids": [a["entity_id"] for a in assets]}, ctx(db_url, T_N)
    )
    assert [i.entity_ids[0] for i in got.new_items] == [a["entity_id"] for a in assets]
    before = await run("get_risk", {"level": "county"}, ctx(db_url, datetime(2024, 9, 24, tzinfo=UTC)))
    assert before.status == "empty"


async def test_outages_and_crews_match_the_ops_pages(client: TestClient, db_url: str) -> None:
    outages = at(client, T_OUT).get("/api/outages").json()
    crews = client.get("/api/crews").json()
    assert outages and crews
    got = await run("get_outages", {}, ctx(db_url, T_OUT))
    total, summary, *rows = got.new_items
    assert total.kind == "county_outage_total"
    assert summary.values["open_outage_events"].value == len(outages)
    assert summary.values["customers_on_these_events"].value == sum(o["customers_out"] for o in outages)
    assert [r.entity_ids[0] for r in rows] == [o["outage_id"] for o in outages[:25]]
    assert [r.values["customers_out"].value for r in rows] == [o["customers_out"] for o in outages[:25]]
    got = await run("get_crews", {}, ctx(db_url, T_OUT))
    summary, *rows = got.new_items
    assert summary.values["crews"].value == len(crews)
    assert summary.values["people"].value == sum(c["headcount"] for c in crews)
    assert [r.entity_ids[0] for r in rows if r.kind == "crew"] == [c["crew_id"] for c in crews[:25]]
    crew_rows = [r for r in rows if r.kind == "crew"]
    assert [r.hints["status"] for r in crew_rows] == [c["status"] for c in crews[:25]]
    plan = client.get("/api/crews/plan").json()
    options = [r for r in rows if r.kind == "crew_plan_option"]
    assert [o.entity_ids[0] for o in options] == [p["plan_id"] for p in plan["plans"]]
    assert [o.values["early_mutual_aid_persons"].value for o in options] == [
        p["early_mutual_aid_persons"] for p in plan["plans"]
    ]


async def test_etr_and_outage_forecast_match_the_forecast_page(client: TestClient, db_url: str) -> None:
    page = at(client, T_END).get("/api/forecasts?target=etr&entity=GLOBAL").json()
    (etr,) = (await run("get_etr", {}, ctx(db_url, T_END))).new_items
    last = page["series"][-1]
    assert (etr.values["p10"].value, etr.values["p50"].value, etr.values["p90"].value) == (
        last["p10"],
        last["p50"],
        last["p90"],
    )
    assert etr.model_version == page["model_version"] and page["forecast_id"] in etr.entity_ids
    fan = at(client, T_N).get("/api/forecasts?target=outages&entity=45003").json()
    (county,) = (
        await run("get_forecast", {"target": "outages", "entity_id": "45003"}, ctx(db_url, T_N))
    ).new_items
    assert county.values["p50"].value == round(fan["series"][-1]["p50"])


async def test_feed_health_and_decisions_match_their_pages(client: TestClient, db_url: str) -> None:
    feeds = at(client, T_N).get("/api/feeds/health").json()
    got = await run("get_feed_health", {}, ctx(db_url, T_N))
    assert [i.entity_ids[0] for i in got.new_items] == [f["source_id"] for f in feeds]
    assert [i.hints["stale"] for i in got.new_items] == ["yes" if f["stale"] else "no" for f in feeds]
    board = client.get("/api/proposals").json()
    assert board
    got = await run("list_decisions", {"limit": 50}, ctx(db_url, T_N))
    assert [i.entity_ids[0] for i in got.new_items] == [p["proposal_id"] for p in board[:50]]
    for item, row in zip(got.new_items, board, strict=False):
        assert item.values["effective_decide_by"].value == datetime.fromisoformat(
            row["effective_decide_by_utc"].replace("Z", "+00:00")
        )
        assert item.hints["severity"] == row["severity"]
