from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from sgw.ingest.testing import ScratchDb, scratch_database, server_available
from sgw.models.restoration.conformal import Calibrator
from sgw.models.restoration.etr import GLOBAL, EtrModel
from sgw.models.restoration.process import ProcessRun
from sgw.models.restoration.publish import FORECAST_TARGET, EtrEstimate, estimates, write

CALS = {(pop, off): Calibrator(0.1, 0.05, 0.02, 100) for pop in ("regional", "global") for off in (0.0, 24.0)}


@pytest.fixture(scope="module")
def published(story: ProcessRun, small_model: EtrModel) -> list[EtrEstimate]:
    return estimates(story, 24.0, small_model, CALS, members=12)


def test_publication_has_the_global_etr_first_then_operating_areas(published: list[EtrEstimate]) -> None:
    assert published[0].scope == "global" and published[0].region_id == GLOBAL
    regions = [e.region_id for e in published[1:]]
    assert regions and all(r.startswith("OPA-") for r in regions)
    assert len({e.estimate_id for e in published}) == len(published)
    for e in published:
        times = [e.p10_utc, e.p25_utc, e.p50_utc, e.p75_utc, e.p90_utc]
        assert times == sorted(times)
        assert e.as_of_utc < e.p10_utc
        assert e.calibrated and e.target.startswith("90 percent")
        assert e.customers_out_now <= e.peak_customers_out


def test_publication_is_deterministic(
    story: ProcessRun, small_model: EtrModel, published: list[EtrEstimate]
) -> None:
    again = estimates(story, 24.0, small_model, CALS, members=12)
    assert [e.model_dump() for e in again] == [e.model_dump() for e in published]


@pytest.fixture
def scratch_db() -> Iterator[ScratchDb]:
    reason = server_available()
    if reason:
        pytest.skip(reason)  # sgw-allow-skip: database tests need the local Postgres stack (port 5434)
    with scratch_database("wp17") as db:
        yield db


def test_write_stores_forecast_rows_snapshot_and_model_once(
    scratch_db: ScratchDb, published: list[EtrEstimate]
) -> None:
    with psycopg.connect(scratch_db.runtime_url, autocommit=True) as conn:
        assert write(conn, published, "0" * 64) == len(published)
        assert write(conn, published, "0" * 64) == 0
        moved = [e.model_copy(update={"p50_utc": e.p75_utc}) for e in published[:1]]
        assert write(conn, moved, "0" * 64) == 1
        assert conn.execute(
            "SELECT valid_at FROM forecast WHERE forecast_id = %s", (moved[0].estimate_id,)
        ).fetchone() == (moved[0].p75_utc,)
        write(conn, published, "0" * 64)
        rows = conn.execute(
            "SELECT entity_id, quantiles->>'p50', valid_at FROM forecast WHERE target = %s ORDER BY 1",
            (FORECAST_TARGET,),
        ).fetchall()
        assert len(rows) == len(published)
        by_id = {e.region_id: e for e in published}
        for entity, p50, valid_at in rows:
            assert valid_at == by_id[entity].p50_utc
            assert p50 == by_id[entity].p50_utc.isoformat()
        snap = conn.execute(
            "SELECT count(*), max(jsonb_array_length(output)) FROM snapshot WHERE kind = 'etr'"
        )
        assert snap.fetchone() == (1, len(published))
        assert conn.execute("SELECT count(*) FROM model_version WHERE name = 'sgw-etr-a6'").fetchone() == (1,)


def test_etr_is_never_overlaid_on_a_replay_curve_from_another_process(published: list[EtrEstimate]) -> None:
    from sgw.models.restoration.publish import replay_county_t90_median, replay_overlay_allowed

    assert replay_county_t90_median() > 0
    assert replay_overlay_allowed() is False
    assert all(e.replay_overlay_allowed is False for e in published)
