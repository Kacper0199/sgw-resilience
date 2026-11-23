"""One seed for a demo database (`sgw seed --demo`), in the order the story needs: K18 users with their
demo passwords, the reference rows and the Helene crew proposal (`run_seed`), the map reference (county
geometry and located synthetic assets, `sgw.reference.load`), the Helene replay into the
ledger, the PS-17 decision queue at advisory N (water twin), the WP-17 ETR publication, the WP-11 risk
picture of every advisory at its issue time (risk, county forecasts, plan diffs), the WP-16 crew plan for
advisory N (SAA job, about 95 s at full size) and the procedure corpus index. Every step is idempotent.
Synthetic data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import psycopg

from sgw.approval.seed import run_seed
from sgw.reference.load import load_map_reference

FIRST_ADVISORY = "N"


@dataclass
class DemoSeedReport:
    users: int = 0
    regions: int = 0
    assets: int = 0
    ledger_head: int = 0
    cases: int = 0
    etr_rows: int = 0
    risk_snapshots: list[str] = field(default_factory=list)
    crew_plan: str | None = None
    corpus: dict[str, int] = field(default_factory=dict)


def seed_risk(conn: psycopg.Connection[Any], scenario: str) -> list[str]:
    """Publish the risk picture of every advisory at its issue time (no-op for snapshots already stored)."""
    from sgw.models.hazard.ensemble import scenario_hazard
    from sgw.models.outage.publisher import publish_tick

    out = []
    for adv in scenario_hazard(scenario).advisories:
        result = publish_tick(conn, adv.issued, scenario)
        if result.snapshot_id is not None:
            out.append(result.snapshot_id)
    return out


def seed_crew_plan(
    conn: psycopg.Connection[Any], scenario: str, advisory: str, opts: Mapping[str, Any] | None = None
) -> str:
    """The stored crew plan for (scenario, advisory); runs the SAA job once when none is stored."""
    from sgw.models.optimise import job

    found = conn.execute(
        "SELECT snapshot_id FROM snapshot WHERE kind = %s AND output->>'scenario' = %s"
        " AND output->>'advisory' = %s ORDER BY as_of DESC, snapshot_id DESC LIMIT 1",
        (job.SNAPSHOT_KIND, scenario, advisory),
    ).fetchone()
    if found is not None:
        return str(found[0])
    job_id = job.enqueue(
        conn, scenario=scenario, advisory=advisory, requested_by="system:seed", **dict(opts or {})
    )
    while (done := job.work_one(conn, run_id=f"seed:{scenario}:{advisory}")) is not None:
        if done.job_id == job_id:
            return done.snapshot_id
    raise RuntimeError(f"crew plan job {job_id} was not run")


def seed_demo(
    dsn: str,
    password: str | None,
    scenario: str = "helene",
    env: Mapping[str, str] | None = None,
    *,
    risk: bool = True,
    crew_plan: bool = True,
    crew_plan_opts: Mapping[str, Any] | None = None,
) -> DemoSeedReport:
    """`env` carries per-persona DEMO_PASSWORD_<USER_ID> values, which win over the shared `password`.
    `risk` and `crew_plan` switch off the two model publications (tests of other steps); `crew_plan_opts`
    passes smaller SAA sizes (tests)."""
    from sgw.agent.rag.corpus import load_corpus
    from sgw.agent.rag.embed import CachedPassages, default_embedder
    from sgw.agent.rag.headers import load_headers
    from sgw.agent.rag.index import build_index
    from sgw.api.users import seed_users
    from sgw.models.clocks import advisory
    from sgw.models.restoration import artefact, publish
    from sgw.pipeline.replay import replay_scenario

    report = DemoSeedReport()
    run_seed(dsn)
    report.users = seed_users(dsn, password, env=env)
    with psycopg.connect(dsn, autocommit=True) as conn:
        mapped = load_map_reference(conn)
        report.regions, report.assets = mapped.regions, mapped.assets
        replayed = replay_scenario(conn, scenario, env={})
        if not (replayed.ok and replayed.ledger.gapless):
            raise RuntimeError(f"replay of {scenario} failed: {replayed.error_failures} error checks")
        report.ledger_head = int(replayed.ledger.max_seq or 0)
        queue = advisory.compute(advisory.member_table(), FIRST_ADVISORY, conn)
        report.cases = len(queue.cases)
        model, cals, doc = artefact.load()
        items = publish.estimates(publish.story_run(), 24.0, model, cals)
        report.etr_rows = int(publish.write(conn, items, doc["data_hash"]))
        if risk:
            report.risk_snapshots = seed_risk(conn, scenario)
        if crew_plan:
            report.crew_plan = seed_crew_plan(conn, scenario, FIRST_ADVISORY, crew_plan_opts)
    with psycopg.connect(dsn) as conn:
        stats = build_index(
            conn, load_corpus(), load_headers(), embedder=default_embedder(), cache=CachedPassages()
        )
    report.corpus = {str(k): int(v) for k, v in dict(stats).items()}
    return report
