"""Risk publisher: on each scenario tick, publish the risk picture of the advisory in force.

A tick is a scenario time. The publisher picks the latest advisory issued at or before it, computes (cached
per advisory) the county fans, asset risk and no-regret shares, and in one transaction writes a `snapshot`
(kind `risk`), its `risk` rows (all counties, the top assets), the county `forecast` rows, the plan diff
against the previous advisory (`snapshot` kind `plan_diff`), the serving model's `model_version` row and the
K2 `RiskSnapshotPublished` event through the outbox; after commit it drains the relay so the event reaches the
ledger. A snapshot is written only when its inputs change (a new advisory or model): the id derives from
scenario, advisory and model, so further ticks under the same advisory are no-ops (`ON CONFLICT DO NOTHING`,
relay dedup); event times are the scenario time of the first tick, so a replay publishes the same bytes.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from sgw.common.telemetry import sgw_span
from sgw.contracts.events import EVENT_MODELS, EnvelopeBase
from sgw.contracts.vocab import Classification, Domain, FeedMode, RunMode, Trust
from sgw.ingest import outbox, relay
from sgw.models.hazard.ensemble import scenario_hazard
from sgw.models.outage.backtest import ARTEFACT_DIR, REPORT_PATH, SERVING_MODEL
from sgw.models.outage.forecast import (
    ENGINE_VERSION,
    TOP_ASSETS,
    TOP_EVENT_ENTITIES,
    AdvisoryRisk,
    advisory_risk,
)
from sgw.models.outage.plan_diff import plan_diff

SOURCE_ID = "sgw-risk-engine"
RISK_NAMESPACE = uuid.UUID("5b0d2f6e-91a4-5c3e-8d27-4e6a1c9f0b83")
FORECAST_TARGET = "county_peak_customers_out"
ORIGIN = "wp11.risk"
EVAL_REPORT = "evals/reports/outage_loso_v3.json"


@dataclass(frozen=True)
class TickResult:
    snapshot_id: str | None
    advisory_label: str | None
    created: bool
    event_seq: int | None
    seconds: float


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_id(scenario: str, label: str, model_name: str) -> str:
    """One snapshot per set of inputs (scenario, advisory, model): ticks inside one advisory add nothing."""
    return f"RSK-{scenario.upper()}-{label.replace('+', 'P')}-{model_name}"


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _region(fips: str) -> str:
    return f"{'SC' if fips.startswith('45') else 'GA'}-{fips}"


def risk_event(scenario: str, risk: AdvisoryRisk, sid: str, as_of: datetime) -> EnvelopeBase:
    top = risk.assets.head(TOP_EVENT_ENTITIES)
    dedup = f"{ORIGIN}:{sid}"
    event: EnvelopeBase = EVENT_MODELS["RiskSnapshotPublished"].model_validate(
        {
            "type": "RiskSnapshotPublished",
            "event_id": uuid.uuid5(RISK_NAMESPACE, dedup),
            "source_id": SOURCE_ID,
            "feed_mode": FeedMode.SYNTHETIC,
            "run_mode": RunMode.REPLAY,
            "event_time": as_of,
            "issued_at": datetime.fromisoformat(risk.issued_utc.replace("Z", "+00:00")),
            "received_at": as_of,
            "known_at": as_of,
            "scenario_known_at": as_of,
            "dedup_key": dedup,
            "classification": Classification.C1,
            "trust": Trust.SYSTEM,
            "domain": Domain.ELECTRIC,
            "payload": {
                "snapshot_id": sid,
                "engine_version": f"{ENGINE_VERSION}+{risk.model_name}",
                "as_of_utc": as_of,
                "top_entities": [
                    {"entity_id": r.section_id, "p_ppm": int(r.p_ppm), "band": r.band}
                    for r in top.itertuples()
                ],
            },
        }
    )
    del scenario
    return event


def snapshot_output(risk: AdvisoryRisk) -> dict[str, Any]:
    return {
        "scenario": risk.scenario,
        "advisory_label": risk.advisory_label,
        "forecast_id": risk.forecast_id,
        "issued_utc": risk.issued_utc,
        "next_advisory_utc": risk.next_advisory_utc,
        "model": risk.model_name,
        "meta": risk.meta,
        "footprint_mean_out": int(risk.counties["mean_out"].sum()),
        "label": "S (synthetic replay); county model trained on real storms without the replayed one",
        "no_regret": [
            {
                "action_id": a.action_id,
                "decision_case_ids": list(a.decision_case_ids),
                "share_ppm": a.share_ppm,
                "members_needed": a.members_needed,
                "members": a.members,
                "rule": a.rule,
            }
            for a in risk.actions
        ],
    }


def _insert_snapshot(conn: psycopg.Connection, sid: str, kind: str, as_of: datetime, output: Any) -> bool:
    cur = conn.execute(
        "INSERT INTO snapshot (snapshot_id, kind, as_of, engine_version, hash, output)"
        " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (snapshot_id) DO NOTHING",
        (sid, kind, as_of, ENGINE_VERSION, _hash(output), Jsonb(output)),
    )
    return cur.rowcount == 1


def _write_risk_rows(conn: psycopg.Connection, sid: str, risk: AdvisoryRisk) -> None:
    rows = [
        (
            sid,
            r.fips,
            "county",
            _region(r.fips),
            Domain.ELECTRIC.value,
            int(r.p_ppm),
            r.band,
            int(r.mean_out),
            Jsonb({"shap_drivers": r.drivers, "p50_out": int(r.q0500_out), "p90_out": int(r.q0900_out)}),
        )
        for r in risk.counties.itertuples()
    ]
    rows += [
        (
            sid,
            r.section_id,
            "asset",
            _region(r.fips),
            Domain.ELECTRIC.value,
            int(r.p_ppm),
            r.band,
            int(r.expected_impact),
            Jsonb(
                {
                    "hazard_z": float(r.hazard_z),
                    "asset_z": float(r.asset_z),
                    "gust_p50_ms": float(r.gust_p50_ms),
                    "county_shap_drivers": r.county_drivers,
                    "critical_ids": [c for c in str(r.critical_ids).split(";") if c],
                }
            ),
        )
        for r in risk.assets.head(TOP_ASSETS).itertuples()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO risk (snapshot_id, entity_id, level, region_id, domain, p_ppm, band,"
            " expected_impact, attribution) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            rows,
        )


def _write_forecasts(conn: psycopg.Connection, risk: AdvisoryRisk) -> None:
    issued = datetime.fromisoformat(risk.issued_utc.replace("Z", "+00:00"))
    horizon = timedelta(hours=scenario_hazard(risk.scenario).family.f("forecast.horizon_h"))
    q_cols = [c for c in risk.counties.columns if c.startswith("q") and c.endswith("_out")]
    rows = [
        (
            f"FC-A2-{risk.forecast_id}-{r['fips']}",
            risk.model_name,
            FORECAST_TARGET,
            r["fips"],
            _region(r["fips"]),
            Domain.ELECTRIC.value,
            issued,
            issued,
            issued + horizon,
            Jsonb({c[1:5]: int(r[c]) for c in q_cols} | {"mean": int(r["mean_out"])}),
        )
        for r in risk.counties.to_dict("records")
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO forecast (forecast_id, model_version, target, entity_id, region_id, domain,"
            " issued_at, known_at, valid_at, quantiles) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (forecast_id) DO NOTHING",
            rows,
        )


def _write_model_version(conn: psycopg.Connection, model_name: str) -> None:
    card = json.loads((ARTEFACT_DIR / model_name / "card.json").read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.is_file() else {}
    metrics = {m["metric"]: m["value"] for m in report.get("metrics", []) if ".helene." in m["metric"]}
    conn.execute(
        "INSERT INTO model_version (model_id, name, version, data_hash, metrics, eval_report, alias)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (model_id) DO UPDATE SET eval_report = EXCLUDED.eval_report",
        (
            f"{model_name}@{card.get('version', '1.0')}",
            model_name,
            str(card.get("version", "1.0")),
            str(card.get("data_sha256", "unknown")),
            Jsonb(metrics),
            EVAL_REPORT,
            "serving",
        ),
    )


def publish_tick(
    conn: psycopg.Connection, as_of: datetime, scenario: str = "helene", model_name: str = SERVING_MODEL
) -> TickResult:
    """Publish the risk snapshot for scenario time `as_of`. `conn` must be idle in autocommit mode."""
    started = time.perf_counter()
    hz = scenario_hazard(scenario)
    adv = hz.advisory_at(as_of)
    if adv is None:
        return TickResult(None, None, False, None, time.perf_counter() - started)
    with sgw_span(
        "models.risk_publish",
        run_id=f"{scenario}:{as_of:%Y%m%dT%H%MZ}",
        classification=Classification.C1,
        user_role="system",
        run_mode=RunMode.REPLAY,
    ):
        risk = advisory_risk(scenario, adv.label, model_name)
        prev = hz.previous(adv)
        diff = plan_diff(advisory_risk(scenario, prev.label, model_name), risk) if prev else None
        sid = snapshot_id(scenario, adv.label, model_name)
        with conn.transaction():
            created = _insert_snapshot(conn, sid, "risk", as_of, snapshot_output(risk))
            if created:
                _write_risk_rows(conn, sid, risk)
                _write_forecasts(conn, risk)
                _write_model_version(conn, model_name)
                if diff is not None:
                    did = f"PDF-{scenario.upper()}-{diff['from_forecast_id']}-{diff['to_forecast_id']}"
                    _insert_snapshot(conn, did, "plan_diff", adv.issued, diff)
                outbox.enqueue(conn, [risk_event(scenario, risk, sid, as_of)], origin=ORIGIN)
        relay.drain(conn)
        row = conn.execute(
            "SELECT ledger_seq FROM event WHERE dedup_key = %s", (f"{ORIGIN}:{sid}",)
        ).fetchone()
    return TickResult(sid, adv.label, created, int(row[0]) if row else None, time.perf_counter() - started)
