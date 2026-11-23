"""Map reference: `sgw seed --demo` (`seed_demo`, about 20 s) on a scratch database puts county
geometry and located synthetic assets behind `/api/regions` and `/api/assets` (PS-17 chain with coordinates),
idempotently and without touching approval inputs."""

from __future__ import annotations

import itertools
import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from sgw.api.app import create_app
from sgw.api.deps import current_user
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk
from sgw.approval.demo_seed import seed_demo
from sgw.approval.seed import run_seed
from sgw.contracts import golden
from sgw.contracts.api_models import Asset, Region
from sgw.reference.load import (
    COUNTIES_PATH,
    WEB_COUNTIES_PATH,
    county_features,
    distance_m,
    load_map_reference,
    placed_assets,
)

from .test_reference_routes import NO_DB, READER

CHAIN = {
    "DEP-AIK-GRANITEVILLE": "fuel_depot",
    "MGEN-HALBERD-500": "portable_generator",
    golden.PS17: "pump_station",
    golden.ZONE: "pressure_zone",
    golden.HOSPITAL: "critical_customer",
    golden.FEEDER_PS17: "feeder",
}

CHAIN_ORDER = ("DEP-AIK-GRANITEVILLE", "MGEN-HALBERD-500", golden.PS17, golden.ZONE, golden.HOSPITAL)
MIN_CHAIN_GAP_M = 800
LOCATION_KEYS = (
    "location_source",
    "location_from",
    "location_offset_m",
    "location_bearing_deg",
    "location_basis",
)


def _approval_inputs(conn: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT asset_id, customers_served, critical_facility,"
        " attributes - %s::text[] FROM asset ORDER BY asset_id",
        (list(LOCATION_KEYS),),
    ).fetchall()


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database("sgw_beui1_m") as url:
        run_seed(url, use_default_ledger=False)
        with psycopg.connect(url, autocommit=True) as conn:
            before = _approval_inputs(conn)
        report = seed_demo(url, "beui1-" + secrets.token_hex(8), risk=False, crew_plan=False)
        assert (report.regions, report.assets) == (len(county_features()), len(placed_assets()))
        with psycopg.connect(url, autocommit=True) as conn:
            again = load_map_reference(conn)
            assert (again.regions, again.assets) == (report.regions, report.assets)
            known = {b[0] for b in before}
            assert [r for r in _approval_inputs(conn) if r[0] in known] == before
        yield url


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    app = create_app(ApiSettings(database_url=db_url, demo_mode=True))
    app.dependency_overrides[current_user] = lambda: READER
    with TestClient(app) as c:
        yield c


def test_every_footprint_county_has_a_bbox(client: TestClient) -> None:
    regions = [Region.model_validate(r) for r in client.get("/api/regions").json()]
    assert len(regions) == len(county_features())
    assert all(r.bbox_e6 is not None for r in regions)
    aiken = next(r for r in regions if r.region_id == golden.REGION_AIKEN)
    assert aiken.name == "Aiken County" and aiken.bbox_e6 is not None
    x0, y0, x1, y1 = aiken.bbox_e6
    ps17 = next(a for a in placed_assets() if a.asset_id == golden.PS17)
    assert x0 <= round(ps17.lon * 1e6) <= x1 and y0 <= round(ps17.lat * 1e6) <= y1


def test_assets_return_the_ps17_chain_with_coordinates(client: TestClient) -> None:
    got: list[Asset] = []
    url: str | None = "/api/assets?limit=10"
    while url:
        r = client.get(url)
        assert r.status_code == 200
        got += [Asset.model_validate(a) for a in r.json()]
        link = r.headers.get("Link")
        url = link.split(";")[0].strip()[1:-1] if link else None
    by_id = {a.asset_id: a for a in got}
    assert len(by_id) == len(got) == len(placed_assets())
    for asset_id, kind in CHAIN.items():
        a = by_id[asset_id]
        assert a.kind == kind and a.region_id == golden.REGION_AIKEN and a.name
    ps17 = by_id[golden.PS17]
    assert (ps17.lon_e6, ps17.lat_e6) == (-81_719_000, 33_564_000)
    assert ps17.name == "PS-17 Cedarfall booster (synthetic)"
    assert by_id[golden.ZONE].lon_e6 > ps17.lon_e6
    assert by_id[golden.HOSPITAL].critical_facility
    assert by_id[golden.YARD_MILLPOND].region_id == golden.REGION_RICHMOND
    assert all("(synthetic)" in (a.name or "") for a in got)


def test_location_provenance_is_recorded(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        rows = dict(
            conn.execute(
                "SELECT asset_id, attributes ->> 'location_from' FROM asset"
                " WHERE attributes ? 'location_source'"
            ).fetchall()
        )
    assert rows[golden.HOSPITAL] == golden.ZONE
    assert rows[golden.ZONE] == golden.PS17
    assert rows["DEP-AIK-GRANITEVILLE"] == "MGEN-HALBERD-500"
    assert rows[golden.PS17] is None
    with psycopg.connect(db_url) as conn:
        basis = conn.execute(
            "SELECT attributes FROM asset WHERE asset_id = %s", (golden.HOSPITAL,)
        ).fetchone()
    assert basis is not None
    assert basis[0]["location_basis"] == "assumed for the map"
    assert basis[0]["location_offset_m"] == 2000 and basis[0]["location_bearing_deg"] == 90


def test_chain_assets_are_at_least_800_m_apart_and_read_west_to_east(client: TestClient) -> None:
    by_id = {a["asset_id"]: Asset.model_validate(a) for a in client.get("/api/assets?limit=1000").json()}
    points = [(by_id[i].lon_e6 / 1e6, by_id[i].lat_e6 / 1e6) for i in CHAIN_ORDER]
    for a, b in itertools.combinations(range(len(points)), 2):
        gap = distance_m(points[a], points[b])
        assert gap >= MIN_CHAIN_GAP_M, (CHAIN_ORDER[a], CHAIN_ORDER[b], round(gap))
    assert [p[0] for p in points] == sorted(p[0] for p in points)


def test_offsets_are_deterministic_and_measured() -> None:
    first, second = placed_assets(), placed_assets()
    assert first == second
    by_id = {a.asset_id: a for a in first}
    for a in first:
        if a.location_from:
            anchor = by_id[a.location_from]
            assert abs(distance_m((a.lon, a.lat), (anchor.lon, anchor.lat)) - (a.offset_m or 0)) < 1.0
            assert 1500 <= (a.offset_m or 0) <= 4000


def test_seed_county_file_is_the_web_map_layer() -> None:
    assert COUNTIES_PATH.read_bytes() == WEB_COUNTIES_PATH.read_bytes()


def test_existing_geometry_and_attribute_keys_are_kept(db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        saved = conn.execute(
            "SELECT asset_id, geom, attributes FROM asset WHERE asset_id = ANY(%s)",
            ([golden.HOSPITAL, golden.ZONE],),
        ).fetchall()
        try:
            conn.execute(
                "UPDATE asset SET geom = ST_SetSRID(ST_MakePoint(-81.5, 33.5), 4326),"
                ' attributes = attributes || \'{"location_basis": "surveyed", "synthetic": false}\'::jsonb'
                " WHERE asset_id = %s",
                (golden.HOSPITAL,),
            )
            conn.execute(
                "UPDATE asset SET attributes = attributes - 'location_offset_m' WHERE asset_id = %s",
                (golden.ZONE,),
            )
            load_map_reference(conn)
            hsp = conn.execute(
                "SELECT ST_X(geom), ST_Y(geom), attributes FROM asset WHERE asset_id = %s", (golden.HOSPITAL,)
            ).fetchone()
            zone = conn.execute("SELECT attributes FROM asset WHERE asset_id = %s", (golden.ZONE,)).fetchone()
        finally:
            for asset_id, geom, attributes in saved:
                conn.execute(
                    "UPDATE asset SET geom = %s::geometry, attributes = %s WHERE asset_id = %s",
                    (geom, Jsonb(attributes), asset_id),
                )
    assert hsp is not None and zone is not None
    assert (hsp[0], hsp[1]) == (-81.5, 33.5)
    assert hsp[2]["location_basis"] == "surveyed" and hsp[2]["synthetic"] is False
    assert zone[0]["location_offset_m"] == 2500
