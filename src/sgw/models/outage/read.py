"""Reads of the published risk picture (WP-11 publisher output) for the API: the risk snapshot in force at a
scenario time, forecast series, the county fans of one advisory and the plan diff N -> N+1.

Only what the publisher wrote is read (K1 `snapshot`, `risk`, `forecast`), and only rows published at or
before the scenario time the caller passes, so a screen never sees an advisory before it is issued. Nothing is
recomputed here. The target names and labels repeat the publishers' constants so the API does not import
the model stack; a test pins them equal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from sgw.common import numbers as numbers_mod
from sgw.contracts.api_models import (
    ActionShare,
    CountyFan,
    CountyForecast,
    CountyOutage,
    CountyOutagesNow,
    ForecastResponse,
    ObservedOutages,
    PlanDiff,
    Provenance,
    QuantileBand,
    RiskItem,
    RiskResponse,
)
from sgw.contracts.vocab import NoRegretVerdict, NumberLabel, RiskBand, UiSeverity
from sgw.generator.config import load_counties

OUTAGE_TARGET = "county_peak_customers_out"
ETR_TARGET = "etr_90pct_restored"
ETR_LABEL = (
    "S (synthetic family-A replay of Helene; model calibrated on family-A storms, see evals/reports/etr.json)"
)
BAND_SEVERITY: dict[RiskBand, UiSeverity] = {
    RiskBand.VERY_HIGH: UiSeverity.CRITICAL,
    RiskBand.HIGH: UiSeverity.SEVERE,
    RiskBand.MODERATE: UiSeverity.ELEVATED,
    RiskBand.LOW: UiSeverity.ADVISORY,
    RiskBand.VERY_LOW: UiSeverity.NORMAL,
}
ACT_NOW_POLICY = "policy_no_regret_act_now_ppm"
C3_POLICY = "policy_c3_aggregation_assets"
TARGETS: dict[str, str] = {"outages": OUTAGE_TARGET, "etr": ETR_TARGET}
UNITS: dict[str, str] = {
    "outages": "customers out at the storm's peak",
    "etr": "hours from issue to 90 percent of the peak customers out restored",
}
OUTAGE_LABEL = "S (synthetic replay); county model trained on real storms without the replayed one"
QUANTILE_KEYS = ("0025", "0100", "0250", "0500", "0750", "0900", "0975")


class NotPublished(LookupError):
    """Nothing matching was published at or before the scenario time."""


def severity_for(band: RiskBand) -> UiSeverity:
    return BAND_SEVERITY[band]


def asset_list_cap() -> int:
    """Ranked asset lists stop at the C3 aggregation limit (DC-39)."""
    return int(numbers_mod.value(C3_POLICY))


def _drivers(attribution: dict[str, Any], level: str) -> list[str]:
    raw = attribution.get("shap_drivers" if level == "county" else "county_shap_drivers") or []
    return [str(d["feature"]) if isinstance(d, dict) else str(d) for d in raw]


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    as_of: datetime
    output: dict[str, Any]


async def risk_snapshot(
    conn: AsyncConnection[Any], scenario: str, at: datetime, advisory: str | None = None
) -> Snapshot | None:
    """The latest risk snapshot of `scenario` published at or before `at` (optionally of one advisory)."""
    sql = (
        "SELECT snapshot_id, as_of, output FROM snapshot WHERE kind = 'risk' AND output->>'scenario' = %s"
        " AND as_of <= %s"
    )
    args: list[Any] = [scenario, at]
    if advisory is not None:
        sql += " AND output->>'advisory_label' = %s"
        args.append(advisory)
    sql += " ORDER BY as_of DESC, snapshot_id DESC LIMIT 1"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        row = await cur.fetchone()
    return None if row is None else Snapshot(row["snapshot_id"], row["as_of"], row["output"])


def _risk_provenance(snap: Snapshot) -> Provenance:
    return Provenance(
        source=f"snapshot:{snap.snapshot_id}",
        model_id=str(snap.output.get("model")),
        as_of=snap.as_of,
        label=NumberLabel.S,
        detail=str(snap.output.get("label") or OUTAGE_LABEL),
    )


async def risk(conn: AsyncConnection[Any], scenario: str, at: datetime, level: str) -> RiskResponse:
    snap = await risk_snapshot(conn, scenario, at)
    if snap is None:
        raise NotPublished(f"no risk snapshot of {scenario} published at or before {at:%Y-%m-%dT%H:%MZ}")
    order = "entity_id" if level != "asset" else "expected_impact DESC, p_ppm DESC, entity_id"
    sql = (
        "SELECT entity_id, level, p_ppm, band, expected_impact, attribution FROM risk"  # noqa: S608
        f" WHERE snapshot_id = %s AND level = %s ORDER BY {order}"
    )
    args: list[Any] = [snap.snapshot_id, level]
    if level == "asset":
        sql += " LIMIT %s"
        args.append(asset_list_cap())
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        rows = await cur.fetchall()
    items = [
        RiskItem(
            entity_id=r["entity_id"],
            level=r["level"],
            p_ppm=r["p_ppm"],
            band=RiskBand(r["band"]),
            severity=severity_for(RiskBand(r["band"])),
            expected_impact=r["expected_impact"],
            drivers=_drivers(r["attribution"] or {}, r["level"]),
        )
        for r in rows
    ]
    return RiskResponse(
        as_of=snap.as_of,
        snapshot_id=snap.snapshot_id,
        items=items,
        advisory_label=snap.output.get("advisory_label"),
        provenance=_risk_provenance(snap),
    )


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _band(target: str, issued: datetime, valid: datetime, q: dict[str, Any]) -> QuantileBand:
    if target == "outages":
        return QuantileBand(
            valid_at=valid,
            p10=float(q["0100"]),
            p50=float(q["0500"]),
            p90=float(q["0900"]),
            p025=float(q["0025"]) if "0025" in q else None,
            p975=float(q["0975"]) if "0975" in q else None,
        )

    def hours(key: str) -> float:
        return round((_iso(str(q[key])) - issued) / timedelta(hours=1), 1)

    return QuantileBand(valid_at=issued, p10=hours("p10"), p50=hours("p50"), p90=hours("p90"))


async def forecast(conn: AsyncConnection[Any], target: str, entity: str, at: datetime) -> ForecastResponse:
    """Every forecast of `target` for `entity` issued at or before `at`, oldest first; ids from the latest.
    `outages`: the county peak fan per advisory (entity = county FIPS). `etr`: time to 90 percent restored in
    hours from each issue (entity = GLOBAL or an operating-area region id)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT forecast_id, model_version, issued_at, known_at, valid_at, quantiles FROM forecast"
            " WHERE target = %s AND entity_id = %s AND known_at <= %s ORDER BY issued_at, forecast_id",
            (TARGETS[target], entity, at),
        )
        rows = await cur.fetchall()
    if not rows:
        raise NotPublished(f"no {target} forecast for {entity} issued at or before {at:%Y-%m-%dT%H:%MZ}")
    latest = rows[-1]
    return ForecastResponse(
        forecast_id=latest["forecast_id"],
        target=target,  # type: ignore[arg-type]
        entity_id=entity,
        model_version=latest["model_version"],
        issued_at=latest["issued_at"],
        series=[_band(target, r["issued_at"], r["valid_at"], r["quantiles"]) for r in rows],
        unit=UNITS[target],
        provenance=Provenance(
            source=f"forecast:{latest['forecast_id']}",
            model_id=latest["model_version"],
            as_of=latest["known_at"],
            label=NumberLabel.S,
            detail=OUTAGE_LABEL if target == "outages" else ETR_LABEL,
        ),
    )


@cache
def _county_names() -> dict[str, tuple[str, int]]:
    return {c.fips: (c.name, c.customers) for c in load_counties()}


async def _case_titles(conn: AsyncConnection[Any], case_ids: set[str]) -> dict[str, str]:
    if not case_ids:
        return {}
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT decision_case_id, title FROM decision_case WHERE decision_case_id = ANY(%s)",
            (sorted(case_ids),),
        )
        return {str(k): str(v) for k, v in await cur.fetchall()}


def _label(titles: dict[str, str], action_id: str, case_ids: list[str]) -> str:
    return next((titles[c] for c in case_ids if c in titles), action_id)


@dataclass(frozen=True)
class CaseDecision:
    open_proposal_id: str | None
    timing: NoRegretVerdict


async def case_decisions(conn: AsyncConnection[Any], at: datetime) -> dict[str, CaseDecision]:
    """Every stored case with its open decision and the Timing Decisions shows for it at `at`: the same
    case graph and the same link rule as the proposal card (`sgw.approval.service.with_links`)."""
    from sgw.approval.repository import CASE_GRAPH, KNOWN_BY
    from sgw.approval.severity import QUEUE_OPEN_STATES
    from sgw.models.clocks.links import case_links, facts_from_rows

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(CASE_GRAPH)
        graph = await cur.fetchall()
        await cur.execute(
            "SELECT DISTINCT ON (decision_case_id) decision_case_id, proposal_id FROM proposal p"  # noqa: S608
            " WHERE state = ANY(%(states)s)"
            f" AND {KNOWN_BY} ORDER BY decision_case_id, created_at DESC, proposal_id DESC",
            {"states": sorted(s.value for s in QUEUE_OPEN_STATES), "known_by": at},
        )
        open_ids = {r["decision_case_id"]: r["proposal_id"] for r in await cur.fetchall()}
    facts = facts_from_rows(graph)
    return {cid: CaseDecision(open_ids.get(cid), case_links(cid, facts, at).timing) for cid in facts}


def _decision_of(decisions: dict[str, CaseDecision], case_ids: list[str]) -> dict[str, Any]:
    known = [decisions[c] for c in case_ids if c in decisions]
    return {
        "proposal_id": next((d.open_proposal_id for d in known if d.open_proposal_id), None),
        "timing": known[0].timing if known else None,
    }


def observed(at: datetime) -> tuple[ObservedOutages | None, dict[str, int]]:
    """The outage feed by `at`: totals now and at the peak so far, and each county's peak so far."""
    from sgw.reports.sources import county_series

    series = county_series()
    hours = sorted(t for t in series if t <= at)
    if not hours:
        return None, {}
    totals = {t: sum(series[t].values()) for t in hours}
    peak_at = max(hours, key=lambda t: (totals[t], -t.timestamp()))
    peaks: dict[str, int] = {}
    for t in hours:
        for fips, customers in series[t].items():
            peaks[fips] = max(peaks.get(fips, 0), customers)
    found = ObservedOutages(
        as_of=hours[-1],
        customers_out_now=totals[hours[-1]],
        peak_customers_out=totals[peak_at],
        peak_at_utc=peak_at,
    )
    return found, peaks


def county_outages_now(at: datetime) -> CountyOutagesNow:
    """Customers out per county at the last feed hour by `at`: the hour `replay_status` reads for the
    Briefing."""
    from sgw.reports.sources import county_series

    series = county_series()
    hours = [t for t in series if t <= at]
    if not hours:
        return CountyOutagesNow(as_of=None, customers_out_now=0, counties=[])
    now = max(hours)
    counties = [CountyOutage(fips=f, customers_out=n) for f, n in sorted(series[now].items()) if n > 0]
    return CountyOutagesNow(
        as_of=now, customers_out_now=sum(c.customers_out for c in counties), counties=counties
    )


async def county_forecast(
    conn: AsyncConnection[Any], scenario: str, at: datetime, advisory: str | None
) -> CountyForecast:
    snap = await risk_snapshot(conn, scenario, at, advisory)
    if snap is None:
        which = f"advisory {advisory}" if advisory else "any advisory"
        raise NotPublished(f"no county forecast for {which} published at or before {at:%Y-%m-%dT%H:%MZ}")
    out = snap.output
    names = _county_names()
    ids = [f"FC-A2-{out['forecast_id']}-{fips}" for fips in names]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT entity_id, quantiles FROM forecast WHERE forecast_id = ANY(%s) AND target = %s"
            " ORDER BY entity_id",
            (ids, OUTAGE_TARGET),
        )
        rows = await cur.fetchall()
    actual, county_peaks = observed(at)
    counties = [
        CountyFan(
            fips=r["entity_id"],
            name=names.get(r["entity_id"], (r["entity_id"], 0))[0],
            customers=names.get(r["entity_id"], ("", 0))[1],
            mean=int(r["quantiles"]["mean"]),
            observed_peak=county_peaks.get(r["entity_id"], 0) if actual else None,
            **{f"q{k}": int(r["quantiles"][k]) for k in QUANTILE_KEYS},
        )
        for r in rows
    ]
    shares = list(out.get("no_regret") or [])
    titles = await _case_titles(conn, {c for a in shares for c in a["decision_case_ids"]})
    meta = out.get("meta") or {}
    return CountyForecast(
        advisory_label=out["advisory_label"],
        issued_utc=_iso(out["issued_utc"]),
        next_advisory_utc=_iso(out["next_advisory_utc"]) if out.get("next_advisory_utc") else None,
        model_version=str(out["model"]),
        members=int(meta.get("members", 0)),
        trained_on=[str(s) for s in meta.get("trained_on", [])],
        counties=counties,
        actions=[
            ActionShare(
                action_id=a["action_id"],
                label=_label(titles, a["action_id"], a["decision_case_ids"]),
                decision_case_ids=a["decision_case_ids"],
                share_ppm=a["share_ppm"],
                members_needed=a["members_needed"],
                members=a["members"],
                rule=a["rule"],
            )
            for a in shares
        ],
        provenance=_risk_provenance(snap),
        observed=actual,
    )


async def plan_diff(conn: AsyncConnection[Any], scenario: str, at: datetime, to: str | None) -> PlanDiff:
    """The stored plan diff into advisory `to` (default: the latest one issued at or before `at`)."""
    sql = (
        "SELECT snapshot_id, as_of, output FROM snapshot WHERE kind = 'plan_diff'"
        " AND output->>'scenario' = %s AND as_of <= %s"
    )
    args: list[Any] = [scenario, at]
    if to is not None:
        sql += " AND output->>'to_advisory' = %s"
        args.append(to)
    sql += " ORDER BY as_of DESC, snapshot_id DESC LIMIT 1"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, args)
        row = await cur.fetchone()
    if row is None:
        which = f"into advisory {to}" if to else "of any advisory"
        raise NotPublished(f"no plan diff {which} published at or before {at:%Y-%m-%dT%H:%MZ}")
    d = row["output"]
    titles = await _case_titles(conn, {c for a in d["actions"] for c in a["decision_case_ids"]})
    decisions = await case_decisions(conn, at)
    actions = [
        {
            **a,
            "label": _label(titles, a["action_id"], a["decision_case_ids"]),
            **_decision_of(decisions, a["decision_case_ids"]),
        }
        for a in d["actions"]
    ]
    model = await _snapshot_model(conn, scenario, d["to_advisory"])
    return PlanDiff.model_validate(
        {
            **{k: d[k] for k in PlanDiff.model_fields if k in d and k not in ("actions", "provenance")},
            "assets": d.get("assets", [])[: asset_list_cap()],
            "actions": actions,
            "act_now_policy_key": ACT_NOW_POLICY,
            "provenance": Provenance(
                source=f"snapshot:{row['snapshot_id']}",
                model_id=model,
                rule_id=ACT_NOW_POLICY,
                as_of=row["as_of"],
                label=NumberLabel.S,
                detail=str(d.get("label") or OUTAGE_LABEL),
            ),
        }
    )


async def _snapshot_model(conn: AsyncConnection[Any], scenario: str, advisory: str) -> str | None:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT output->>'model' FROM snapshot WHERE kind = 'risk' AND output->>'scenario' = %s"
            " AND output->>'advisory_label' = %s ORDER BY as_of DESC LIMIT 1",
            (scenario, advisory),
        )
        row = await cur.fetchone()
    return None if row is None else row[0]
