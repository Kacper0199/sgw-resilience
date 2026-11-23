"""Over HTTP on a migrated scratch database with the real app lifespan: `/api/regions`,
`/api/assets` (filters, C0/C1 only, keyset pages, ETag/304) and the public `/api/auth/config`."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import psycopg
import pytest
from fastapi.testclient import TestClient

from sgw.api.app import create_app
from sgw.api.deps import current_user
from sgw.api.sessions import AuthUser
from sgw.api.settings import ApiSettings
from sgw.approval import testkit as tk
from sgw.contracts.api_models import Asset, AuthConfig, Region
from sgw.contracts.vocab import ApprovalFunction, Domain

NO_DB = "no Postgres: set SGW_TEST_DATABASE_URL or run the local stack"
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
SQUARE = "ST_GeomFromText('MULTIPOLYGON(((-82 33.2,-81.2 33.2,-81.2 33.8,-82 33.8,-82 33.2)))', 4326)"
ASSETS = (
    ("BEUI-A-SPOOLWICK-SUB", "electric", "substation", "SC-45003", "POINT(-81.7 33.5)", "C1", None),
    ("BEUI-B-QUILLMERE-PS", "water", "pump_station", "SC-45003", "POINT(-81.6 33.4)", "C0", None),
    (
        "BEUI-C-FERNHOLLOW-FDR",
        "electric",
        "feeder",
        "GA-13245",
        "LINESTRING(-82.1 33.4,-82.0 33.45)",
        "C1",
        None,
    ),
    ("BEUI-D-VAULTED-SCADA", "electric", "control_center", "SC-45003", "POINT(-81.65 33.45)", "C2", None),
    ("BEUI-E-NOGEOM-YARD", "electric", "staging_yard", "SC-45003", None, "C1", None),
    (
        "BEUI-F-RETIRED-SUB",
        "electric",
        "substation",
        "SC-45003",
        "POINT(-81.7 33.6)",
        "C1",
        "[1990-01-01,2000-01-01)",
    ),
)


@pytest.fixture(scope="module")
def db_url() -> Iterator[str]:
    if tk.admin_dsn() is None:
        pytest.skip(NO_DB)  # sgw-allow-skip: needs Postgres
    with tk.scratch_database("sgw_beui1_t") as url:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                f"INSERT INTO region (region_id, state, county_fips, name, geom) VALUES"  # noqa: S608
                f" ('SC-45003', 'SC', '45003', 'Aiken County', {SQUARE}),"
                " ('GA-13245', 'GA', '13245', 'Richmond County', NULL)"
            )
            for asset_id, domain, kind, region, wkt, cls, valid in ASSETS:
                conn.execute(
                    "INSERT INTO asset (asset_id, domain, kind, region_id, geom, classification, valid)"
                    " VALUES (%s, %s, %s, %s, ST_GeomFromText(%s, 4326), %s,"
                    " coalesce(%s::tstzrange, tstzrange('-infinity', 'infinity')))",
                    (asset_id, domain, kind, region, wkt, cls, valid),
                )
        yield url


def _client(db_url: str, *, demo_mode: bool = True, signed_in: bool = True) -> TestClient:
    settings = ApiSettings(database_url=db_url, demo_mode=demo_mode, cookie_secure=not demo_mode)
    app = create_app(settings)
    if signed_in:
        app.dependency_overrides[current_user] = lambda: READER
    return TestClient(app)


@pytest.fixture(scope="module")
def client(db_url: str) -> Iterator[TestClient]:
    with _client(db_url) as c:
        yield c


def _ids(body: list[dict[str, Any]]) -> list[str]:
    return [Asset.model_validate(a).asset_id for a in body]


def test_reads_need_a_session(db_url: str) -> None:
    with _client(db_url, signed_in=False) as anon:
        for path in ("/api/regions", "/api/assets", "/api/assets/BEUI-A-SPOOLWICK-SUB"):
            r = anon.get(path)
            assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_regions_with_bbox_in_microdegrees(client: TestClient) -> None:
    r = client.get("/api/regions")
    assert r.status_code == 200
    regions = {x.region_id: x for x in (Region.model_validate(i) for i in r.json())}
    assert regions["SC-45003"].bbox_e6 == (-82_000_000, 33_200_000, -81_200_000, 33_800_000)
    assert regions["GA-13245"].bbox_e6 is None
    assert list(regions) == sorted(regions)


def test_assets_are_public_classes_with_geometry_valid_now(client: TestClient) -> None:
    r = client.get("/api/assets")
    assert r.status_code == 200
    assert _ids(r.json()) == ["BEUI-A-SPOOLWICK-SUB", "BEUI-B-QUILLMERE-PS", "BEUI-C-FERNHOLLOW-FDR"]
    assert {a["classification"] for a in r.json()} <= {"C0", "C1"}
    spool = Asset.model_validate(r.json()[0])
    assert (spool.lon_e6, spool.lat_e6) == (-81_700_000, 33_500_000)
    line = Asset.model_validate(r.json()[2])
    assert -82_100_000 <= line.lon_e6 <= -82_000_000 and 33_400_000 <= line.lat_e6 <= 33_450_000
    assert "Link" not in r.headers


def test_c2_and_missing_assets_are_404(client: TestClient) -> None:
    assert client.get("/api/assets/BEUI-A-SPOOLWICK-SUB").json()["asset_id"] == "BEUI-A-SPOOLWICK-SUB"
    for asset_id in ("BEUI-D-VAULTED-SCADA", "BEUI-E-NOGEOM-YARD", "BEUI-F-RETIRED-SUB", "NOPE"):
        r = client.get(f"/api/assets/{asset_id}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "ASSET_NOT_FOUND"


def test_filters_by_domain_region_and_bbox(client: TestClient) -> None:
    assert _ids(client.get("/api/assets?domain=water").json()) == ["BEUI-B-QUILLMERE-PS"]
    assert _ids(client.get("/api/assets?region=GA-13245").json()) == ["BEUI-C-FERNHOLLOW-FDR"]
    both = client.get("/api/assets?region=GA-13245&region=SC-45003&domain=electric").json()
    assert _ids(both) == ["BEUI-A-SPOOLWICK-SUB", "BEUI-C-FERNHOLLOW-FDR"]
    assert _ids(client.get("/api/assets?bbox=-81.75,33.45,-81.65,33.55").json()) == ["BEUI-A-SPOOLWICK-SUB"]
    assert client.get("/api/assets?bbox=10,10,11,11").json() == []


@pytest.mark.parametrize(
    "query",
    [
        "bbox=1,2,3",
        "bbox=a,b,c,d",
        "bbox=-81,33,-82,34",
        "bbox=-200,0,0,1",
        "bbox=nan,0,1,1",
        "limit=0",
        "limit=1001",
        "domain=gas",
    ],
)
def test_bad_queries_are_422(client: TestClient, query: str) -> None:
    r = client.get(f"/api/assets?{query}")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_keyset_pages_follow_the_link_header(client: TestClient) -> None:
    seen: list[str] = []
    url = "/api/assets?domain=electric&limit=1"
    for _ in range(5):
        r = client.get(url)
        assert r.status_code == 200
        seen += _ids(r.json())
        link = r.headers.get("Link")
        if link is None:
            break
        target, rel = link.split(";")
        assert rel.strip() == 'rel="next"'
        url = target.strip()[1:-1]
        params = parse_qs(urlsplit(url).query)
        assert params["domain"] == ["electric"] and params["limit"] == ["1"]
    assert seen == ["BEUI-A-SPOOLWICK-SUB", "BEUI-C-FERNHOLLOW-FDR"]


def test_etag_and_304(client: TestClient) -> None:
    first = client.get("/api/assets")
    tag = first.headers["ETag"]
    assert first.headers["Cache-Control"] == "private, no-cache"
    again = client.get("/api/assets", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b"" and again.headers["ETag"] == tag
    other = client.get("/api/assets?domain=water", headers={"If-None-Match": tag})
    assert other.status_code == 200 and other.headers["ETag"] != tag
    regions = client.get("/api/regions")
    assert client.get("/api/regions", headers={"If-None-Match": regions.headers["ETag"]}).status_code == 304


@pytest.mark.parametrize("demo_mode", [True, False])
def test_auth_config_is_public_and_reflects_demo_mode(db_url: str, demo_mode: bool) -> None:
    with _client(db_url, demo_mode=demo_mode, signed_in=False) as anon:
        r = anon.get("/api/auth/config")
        assert r.status_code == 200
        assert r.json() == {"demo_mode": demo_mode}
        assert AuthConfig.model_validate(r.json()).demo_mode is demo_mode
        assert r.headers["Cache-Control"] == "public, max-age=60"
        assert anon.get("/api/me").status_code == 401


def test_list_withholds_criticality_but_the_single_asset_carries_it(client: TestClient, db_url: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE asset SET criticality = 4 WHERE asset_id = 'BEUI-A-SPOOLWICK-SUB'")
    listed = client.get("/api/assets").json()
    assert listed and all(a["criticality"] is None for a in listed)
    one = client.get("/api/assets/BEUI-A-SPOOLWICK-SUB").json()
    assert one["criticality"] == 4
