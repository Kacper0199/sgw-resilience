"""One executor per read-only tool. Each reads the REST page's read model at the injected time and returns
evidence items: ids and plain labels for the model, every number as a slot value that code renders.

Executors return unnumbered items (`id="E1"`); the registry numbers them in the worker's ledger. A read
model with nothing for this time raises `NotAvailable`, which the registry turns into an `empty` answer.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from functools import cache
from typing import Any

from sgw.agent.render.evidence import HINT_VALUE_RE, EvidenceItem, SlotValue
from sgw.agent.tools.context import ToolContext
from sgw.agent.tools.reads import NotAvailable
from sgw.contracts.base import PPM_SCALE
from sgw.contracts.vocab import Classification, RunMode, Trust

Executor = Callable[[dict[str, Any], ToolContext], Awaitable[list[EvidenceItem]]]

MAX_ROWS = 10
MAX_FIELD_ROWS = 25
WHATIF_ALIASES = {"advisory_shift": "track_east", "crew_shift": "aid_late"}
SYNTHETIC = "synthetic SGW replay data"


@cache
def county_names() -> dict[str, tuple[str, str]]:
    from sgw.generator.config import load_counties

    return {c.fips: (c.name, c.st) for c in load_counties()}


def county_label(fips: str) -> str:
    name, state = county_names().get(fips, ("", ""))
    return f"{name} County, {state} ({fips})" if name else f"county {fips}"


def hint(value: str) -> str | None:
    token = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return token if re.match(HINT_VALUE_RE, token) and not re.search(r"\d", token) else None


def hints(**pairs: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in pairs.items():
        value = hint(raw) if raw is not None else None
        if value is not None:
            out[key] = value
    return out


def when(value: datetime) -> SlotValue:
    return SlotValue(value=value, format="utc_minute")


def count(value: float, unit: str | None = None) -> SlotValue:
    return SlotValue(value=round(value), format="count", unit=unit)


def share(fraction: float) -> SlotValue:
    return SlotValue(value=round(fraction * PPM_SCALE), format="percent_ppm")


def item(
    ctx: ToolContext,
    kind: str,
    label: str,
    citation: str,
    *,
    values: dict[str, SlotValue] | None = None,
    entity_ids: list[str | None] | None = None,
    classification: Classification = Classification.C1,
    model_version: str | None = None,
    as_of: datetime | None = None,
    **extra: Any,
) -> EvidenceItem:
    return EvidenceItem(
        id="E1",
        kind=kind,
        label=label[:200],
        as_of=as_of or ctx.at,
        citation=citation,
        classification=classification,
        trust=Trust.SYSTEM,
        model_version=model_version,
        values=values or {},
        entity_ids=[e for e in dict.fromkeys(entity_ids or []) if e],
        **extra,
    )


async def get_risk(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    level = args["level"]
    if level == "h3":
        raise NotAvailable("hexagon risk is not served; ask for county or asset level")
    body = await ctx.reads.risk(ctx.at, level)
    wanted = set(args.get("entity_ids") or [])
    rows = [r for r in body.items if not wanted or r.entity_id in wanted]
    if not wanted:
        rows = sorted(rows, key=lambda r: (-r.p_ppm, -r.expected_impact, r.entity_id))[:MAX_ROWS]
    model = body.provenance.model_id if body.provenance else None
    out = []
    for r in rows:
        name = county_label(r.entity_id) if level == "county" else f"asset {r.entity_id}"
        out.append(
            item(
                ctx,
                "outage_risk",
                f"Outage risk for {name}",
                f"risk snapshot {body.snapshot_id} ({SYNTHETIC})",
                values={
                    "p": SlotValue(value=r.p_ppm, format="percent_ppm"),
                    "expected_out": count(r.expected_impact),
                },
                entity_ids=[r.entity_id],
                classification=Classification.C1 if level == "county" else Classification.C2,
                model_version=model,
                as_of=body.as_of,
                band=r.band,
                hints=hints(
                    severity=r.severity.value, level=level, driver=r.drivers[0] if r.drivers else None
                ),
            )
        )
    return out


async def _forecast_item(ctx: ToolContext, target: str, entity: str) -> EvidenceItem:
    body = await ctx.reads.forecast(ctx.at, target, entity)
    latest = body.series[-1]
    trend = None
    if len(body.series) > 1:
        before = body.series[-2].p50
        trend = "unchanged" if latest.p50 == before else ("higher" if latest.p50 > before else "lower")
    if target == "etr":
        label = f"Estimated time to restore for {entity}, hours from the forecast issue"
        values = {k: SlotValue(value=getattr(latest, k), format="hours") for k in ("p10", "p50", "p90")}
    else:
        label = f"Peak customers out forecast for {county_label(entity)}"
        values = {k: count(getattr(latest, k)) for k in ("p10", "p50", "p90")}
    values["issued"] = when(body.issued_at)
    return item(
        ctx,
        "etr_forecast" if target == "etr" else "outage_forecast",
        label,
        f"forecast {body.forecast_id} ({SYNTHETIC})",
        values=values,
        entity_ids=[entity, body.forecast_id],
        model_version=body.model_version,
        as_of=body.issued_at,
        hints=hints(trend_since_previous_issue=trend),
    )


async def get_forecast(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    if args["target"] not in ("outages", "etr"):
        raise NotAvailable(f"no {args['target']} forecast is published to the copilot")
    return [await _forecast_item(ctx, args["target"], args["entity_id"])]


async def get_etr(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    return [await _forecast_item(ctx, "etr", args.get("entity_id") or "GLOBAL")]


async def get_outages(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    pack = getattr(ctx.reads, "pack", None)
    if pack is not None:
        return _pack_outages(ctx, pack)
    rows = await ctx.reads.outages(ctx.at)
    feeders = set(args.get("feeder_ids") or [])
    picked = [
        o
        for o in rows
        if (not feeders or o.feeder_id in feeders)
        and (not args.get("only_critical") or o.critical_facility_ids)
    ]
    out = _county_outage_total(ctx)
    out.append(
        item(
            ctx,
            "outage_summary",
            "Open outage events logged on SGW feeders"
            + (" asked about" if feeders else "")
            + (
                " (a narrower count than the county total: only events in SGW's own outage log)"
                if out
                else ""
            ),
            f"OMS outage events in the ledger ({SYNTHETIC})",
            values={
                "open_outage_events": count(len(picked)),
                "customers_on_these_events": count(sum(o.customers_out for o in picked)),
            },
            entity_ids=sorted(feeders),
        )
    )
    for o in picked[:MAX_FIELD_ROWS]:
        crit = ", ".join(o.critical_facility_ids)
        out.append(
            item(
                ctx,
                "outage",
                f"Outage {o.outage_id} on feeder {o.feeder_id}"
                + (f", critical facilities {crit}" if crit else ""),
                f"OMS outage event ({SYNTHETIC})",
                values={"customers_out": count(o.customers_out), "started": when(o.started_at)},
                entity_ids=[o.outage_id, o.feeder_id, *o.critical_facility_ids],
                hints=hints(critical_facility="yes" if crit else "no"),
            )
        )
    return out


def _county_outage_total(ctx: ToolContext) -> list[EvidenceItem]:
    """The Briefing's measure: customers without power across the storm counties, from the replayed curve."""
    from sgw.reports.sources import replay_status

    pack = getattr(ctx.reads, "pack", None)
    if pack is not None:
        return _pack_outages(ctx, pack)
    try:
        status = replay_status(ctx.at)
    except ValueError:
        return []
    return [
        item(
            ctx,
            "county_outage_total",
            "Customers without power across the storm counties (the number on the Briefing page)",
            "county outage curve replayed for the scenario (public EAGLE-I shape, synthetic SGW replay data)",
            values={
                "customers_out": count(status.customers_out_now),
                "counties_with_outages": count(status.counties_out),
                "peak_customers_out": count(status.peak_customers_out),
                "peak_at": when(status.peak_at),
            },
            classification=Classification.C0,
            as_of=status.as_of,
            hints=hints(trend=status.trend),
        )
    ]


async def get_crews(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    pack = getattr(ctx.reads, "pack", None)
    rows = await ctx.reads.crews(ctx.at)
    if pack is not None and not rows:
        if found := _pack_crews(ctx, pack):
            return found
        raise NotAvailable(f"no crews are scripted at this time ({pack.label})")
    source = f"{pack.label}: scripted crew roster" if pack is not None else None
    wanted = {s.lower() for s in args.get("status") or []}
    picked = [c for c in rows if not wanted or c.status.value in wanted]
    by_status: dict[str, int] = {}
    for c in picked:
        by_status[c.status.value] = by_status.get(c.status.value, 0) + 1
    out = [
        item(
            ctx,
            "crew_summary",
            "Crews by status at this time",
            source or f"crew status events in the ledger ({SYNTHETIC})",
            values={
                "crews": count(len(picked)),
                "crews_listed_below": count(min(len(picked), MAX_FIELD_ROWS)),
                "people": count(sum(c.headcount for c in picked)),
                **{status: count(n) for status, n in sorted(by_status.items())},
            },
        )
    ]
    for c in picked[:MAX_FIELD_ROWS]:
        values = {"headcount": count(c.headcount)}
        if c.shift_end is not None:
            values["shift_end"] = when(c.shift_end)
        out.append(
            item(
                ctx,
                "crew",
                f"Crew {c.crew_id}, {c.status.value.replace('_', ' ')}"
                + (f" at {c.location_id}" if c.location_id else ""),
                source or f"crew status event ({SYNTHETIC})",
                values=values,
                entity_ids=[c.crew_id, c.location_id],
                hints=hints(status=c.status.value),
            )
        )
    if not wanted:
        out.extend(await _crew_plan_items(ctx))
        if pack is None:
            out.extend(_mobile_resource_items(ctx))
    return out


def _pack_outages(ctx: ToolContext, pack: Any) -> list[EvidenceItem]:
    """A scenario pack's scripted customers out (the Briefing number of that scenario) and the critical
    facilities it scripts without power at this time."""
    from sgw.scenarios.reads import status as pack_status

    status = pack_status(pack, ctx.at)
    out: list[EvidenceItem] = []
    if status is not None:
        out.append(
            item(
                ctx,
                "county_outage_total",
                f"Customers without power across the {pack.title} exercise counties (the number on the"
                " Briefing page)",
                f"{pack.label}: scripted for the exercise, not modelled",
                values={
                    "customers_out": count(status.customers_out_now),
                    "counties_with_outages": count(status.counties_out),
                    "peak_customers_out": count(status.peak_customers_out),
                    "peak_at": when(status.peak_at),
                },
                classification=Classification.C0,
                as_of=status.as_of,
                hints=hints(trend=status.trend),
            )
        )
    names = {a.asset_id: a.name for a in pack.msel.assets}
    down = pack.facilities_out(ctx.at)
    out.append(
        item(
            ctx,
            "facilities_summary",
            "Critical facilities without power in the exercise at this time"
            + (": none" if not down else "")
            + "; feeder outage events are not modelled for this scenario",
            f"{pack.label}: scripted for the exercise",
            values={"facilities_out": count(len(down)), "facilities_watched": count(len(pack.facilities))},
            classification=Classification.C0,
        )
    )
    out.extend(
        item(
            ctx,
            "facility_out",
            f"Critical facility without power: {names.get(fid, fid)}",
            f"{pack.label}: scripted for the exercise",
            entity_ids=[fid],
            classification=Classification.C0,
        )
        for fid in down
    )
    return out


def _pack_crews(ctx: ToolContext, pack: Any) -> list[EvidenceItem]:
    counts = pack.crew_counts(ctx.at)
    if not counts:
        return []
    return [
        item(
            ctx,
            "crew_summary",
            f"Crews by status in the {pack.title} exercise (counts only; no crew roster is modelled)",
            f"{pack.label}: scripted for the exercise",
            values={"crews": count(sum(counts.values())), **{k: count(v) for k, v in sorted(counts.items())}},
            classification=Classification.C0,
        )
    ]


@cache
def _mobile_resources() -> tuple[tuple[str, str, str], ...]:
    import yaml

    from sgw.rules.zones import RULES_PATH

    raw = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return tuple((rid, r["kind"], r["name"]) for rid, r in sorted(raw.get("resources", {}).items()))


def _mobile_resource_items(ctx: ToolContext) -> list[EvidenceItem]:
    """Portable generators, fuel trucks and water tankers the zone rules can send, at their home depot."""
    out = []
    for rid, kind, name in _mobile_resources():
        size = re.search(r"([\d,]+) (kW|gal)", name)
        out.append(
            item(
                ctx,
                "mobile_resource",
                f"{kind.replace('_', ' ').capitalize()} {rid}, staged at Graniteville depot"
                " (DEP-AIK-GRANITEVILLE) near Aiken",
                "zone rules resource list; staged outside the hazard zone (synthetic SGW scenario data)",
                values={"capacity": count(int(size[1].replace(",", "")), size[2])} if size else None,
                entity_ids=[rid, "DEP-AIK-GRANITEVILLE"],
                hints=hints(resource=kind),
            )
        )
    return out


async def _crew_plan_items(ctx: ToolContext) -> list[EvidenceItem]:
    try:
        plan = await ctx.reads.crew_plan(ctx.at)
    except NotAvailable:
        return []
    citation = "SAA crew plan in force; the optimiser does not recommend, approvers decide"
    return [
        item(
            ctx,
            "crew_plan_option",
            f"Crew plan option {o.plan_id}: {o.title}",
            citation,
            values={
                "early_mutual_aid_persons": count(o.early_mutual_aid_persons),
                "own_groups_staged": count(o.own_groups_staged),
                "mutual_aid_usd": count(o.expected_cost.total_mutual_aid_usd, "USD"),
                "expected_customer_hours": count(o.out_of_sample.expected_customer_hours),
                "p90_customer_hours": count(o.out_of_sample.p90_customer_hours),
            },
            entity_ids=[o.plan_id, *sorted(o.yards)],
            model_version=plan.engine_version,
            as_of=plan.issued_utc,
            hints=hints(risk=o.risk),
        )
        for o in plan.plans
    ]


async def list_anomalies(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    if args.get("domain") == "electric":
        raise NotAvailable("the anomaly detector watches water telemetry only")
    rows = (await ctx.reads.anomalies(ctx.at))[: args.get("limit") or 20]
    return [
        item(
            ctx,
            "water_anomaly",
            f"{a.anomaly_class.replace('_', ' ').capitalize()} alarm on sensor {a.entity_id}",
            "A7/A8 water anomaly and spoof detector (synthetic SCADA telemetry)",
            values={
                "detected": when(a.detected_at),
                "score": SlotValue(value=a.score_ppm, format="percent_ppm"),
            },
            entity_ids=[a.anomaly_id, a.entity_id],
            model_version="anomaly.a7_a8",
            hints=hints(alarm=a.anomaly_class, status=a.status),
        )
        for a in rows
    ]


async def get_feed_health(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    wanted = set(args.get("source_ids") or [])
    at = None if ctx.injected.run_mode is RunMode.LIVE else ctx.at
    rows = [f for f in await ctx.reads.feeds(at) if not wanted or f.source_id in wanted]
    out = []
    for f in rows:
        values = {"freshness_limit": SlotValue(value=f.freshness_limit_s / 60, format="minutes")}
        if f.ingest_lag_s is not None:
            values["ingest_lag"] = SlotValue(value=f.ingest_lag_s / 60, format="minutes")
        if f.product_age_s is not None:
            values["product_age"] = SlotValue(value=f.product_age_s / 60, format="minutes")
        out.append(
            item(
                ctx,
                "feed_health",
                f"{f.display_name or f.source_id} feed ({f.source_id})",
                "feed health table (ingest monitor)",
                values=values,
                entity_ids=[f.source_id],
                classification=Classification.C0,
                hints=hints(stale="yes" if f.stale else "no", feed_mode=f.feed_mode.value),
            )
        )
    return out


def _whatif_values(cell: Any) -> dict[str, SlotValue]:
    values = {
        "customer_hours": count(cell.customer_hours),
        "customers_affected": count(cell.customers_affected),
        "peak_customers_out": count(cell.peak_customers_out),
        "change_in_customer_hours": SlotValue(
            value=round(cell.delta_customer_hours_pct * 10_000), format="percent_ppm"
        ),
    }
    if cell.hours_peak_to_90pct is not None:
        values["hours_peak_to_most_restored"] = SlotValue(value=cell.hours_peak_to_90pct, format="hours")
    if cell.peak_utc:
        values["peak"] = when(datetime.fromisoformat(cell.peak_utc.replace("Z", "+00:00")))
    return values


async def run_what_if(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    grid = await ctx.reads.whatif()
    ids = {s.id: s for s in grid.scenarios}
    asked = str(args.get("parameters", {}).get("scenario_id") or WHATIF_ALIASES.get(args["scenario"], ""))
    if asked and asked not in ids:
        raise NotAvailable(f"this what-if is not precomputed; available: {', '.join(sorted(ids))}")
    chosen = [ids[asked]] if asked else list(grid.scenarios)
    citation = f"precomputed what-if grid ({SYNTHETIC})"
    out = [
        item(
            ctx,
            "whatif_baseline",
            "What-if baseline: the storm as forecast",
            citation,
            values=_whatif_values(grid.baseline),
        )
    ]
    for s in chosen:
        direction = (
            "same"
            if s.delta_customer_hours_pct == 0
            else ("worse" if s.delta_customer_hours_pct > 0 else "better")
        )
        out.append(
            item(
                ctx,
                "whatif_scenario",
                f"What-if: {s.title}",
                citation,
                values=_whatif_values(s),
                entity_ids=[s.id],
                hints=hints(versus_baseline=direction),
            )
        )
    return out


def _board_order(p: Any) -> tuple[str, str, str, str, str]:
    """Clock first, then case, owner and state: an order that never depends on run-specific proposal ids."""
    due = p.effective_decide_by_utc or p.decide_by_utc
    owner = p.owner_function.value if p.owner_function else ""
    return (due.isoformat() if due else "~", p.decision_case_id, owner, p.state.value, p.title)


async def missed_cases(reads: Any, at: datetime) -> list[Any]:
    """Decisions whose deadline passed with no proposal; none where the reads cannot tell."""
    read = getattr(reads, "missed_cases", None)
    return list(await read(at)) if read is not None else []


WAITING = frozenset({"proposed", "in_review", "escalated"})


def cut(rows: list[Any], limit: int) -> list[Any]:
    """The first `limit` rows in board order; when the list is longer, the decisions still waiting on signers
    are kept first, so a long day of closed decisions never pushes the open ones out of the answer."""
    if len(rows) <= limit:
        return rows
    waiting = [r for r in rows if r.state.value in WAITING]
    kept = {id(r) for r in (waiting + [r for r in rows if r.state.value not in WAITING])[:limit]}
    return [r for r in rows if id(r) in kept]


async def list_decisions(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    """The decision queue as the Decisions page shows it: no drafts; who signs, who has signed and who owns
    each decision in team names, so an answer never has to guess them or echo an internal code. Without a
    state filter, a decision whose deadline passed with no proposal follows as missed (Decisions > Closed)."""
    states = args.get("states") or None
    limit = args.get("limit") or 20
    rows = sorted(await ctx.reads.decisions(ctx.at, states), key=_board_order)
    listed = cut([r for r in rows if r.state.value != "draft"], limit)
    out = []
    for p in listed:
        values = {"decide_by": when(p.decide_by_utc), "effective_decide_by": when(p.effective_decide_by_utc)}
        out.append(
            item(
                ctx,
                "decision",
                board_label(p),
                "decision board",
                values=values,
                entity_ids=[p.proposal_id, p.decision_case_id],
                hints=hints(
                    state=p.state.value,
                    severity=p.severity.value,
                    critical_path="on" if p.on_critical_path else "off",
                    due=due_window(p.effective_decide_by_utc, ctx.at),
                ),
            )
        )
    for c in (await missed_cases(ctx.reads, ctx.at) if states is None else [])[: limit - len(listed)]:
        out.append(
            item(
                ctx,
                "decision",
                f"{c.title} ({c.decision_case_id}), missed, no proposal before its deadline",
                "decision board",
                values={"effective_decide_by": when(c.effective_decide_by)},
                entity_ids=[c.decision_case_id],
                hints=hints(state="no_proposal", due="passed"),
            )
        )
    return out


def teams(functions: Any) -> str:
    from sgw.api.readmodels.notifications import FUNCTION_LABEL

    names = [FUNCTION_LABEL.get(str(getattr(f, "value", f)), str(getattr(f, "value", f))) for f in functions]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 2 else names) or "none"


def board_label(p: Any) -> str:
    signed = [a.function for a in p.approvals if str(getattr(a.decision, "value", a.decision)) != "reject"]
    parts = [
        f"{p.title} ({p.decision_case_id}), {p.state.value.replace('_', ' ')}",
        f"signed by {teams(p.functions_required)}",
        f"signatures so far: {teams(signed)}",
    ]
    if p.owner_function:
        parts.append(f"owned by {teams([p.owner_function])}")
    return ", ".join(parts)


DUE_WINDOWS: tuple[tuple[timedelta, str], ...] = (
    (timedelta(hours=1), "next_hour"),
    (timedelta(hours=3), "next_three_hours"),
    (timedelta(hours=6), "next_six_hours"),
    (timedelta(hours=24), "next_day"),
)


def due_window(due: datetime, now: datetime) -> str:
    """How far the effective decide-by is from the scenario time, in closed words (the model sees no slot
    values, so "what is due in the next three hours" needs this hint to be answerable)."""
    left = due - now
    if left < timedelta(0):
        return "passed"
    return next((word for span, word in DUE_WINDOWS if left <= span), "later")


async def get_readiness(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    rows = await ctx.reads.readiness()
    picked = [
        r
        for r in rows
        if (not args.get("domain") or r.domain.value == args["domain"])
        and (not args.get("status") or r.status == args["status"])
    ]
    return [
        item(
            ctx,
            "readiness_check",
            f"{r.title} ({r.item_id})",
            "pre-season readiness register",
            values={"due": when(r.due_utc)} if r.due_utc else {},
            entity_ids=[r.item_id],
            hints=hints(status=r.status, domain=r.domain.value, owner=r.owner_function.value),
        )
        for r in picked
    ]


def _attr(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _utc(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


async def list_outage_surges(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    report = await ctx.reads.surges(
        ctx.at, args.get("county_fips") or None, bool(args.get("active_only")), args.get("limit") or 20
    )
    model = _attr(report, "model_version")
    citation = f"{_attr(report, 'source') or 'outage surge detector'} (public EAGLE-I outage data)"
    summary: dict[str, SlotValue] = {
        "counties_monitored": count(_attr(report, "counties_monitored") or 0),
        "counties_surging": count(_attr(report, "counties_surging") or 0),
        "surges": count(_attr(report, "surges_total") or 0),
    }
    if _attr(report, "data_through"):
        summary["data_through"] = when(_utc(_attr(report, "data_through")))
    out = [
        item(
            ctx,
            "outage_surge_summary",
            "Outage surge detector over the storm footprint counties",
            citation,
            values=summary,
            classification=Classification.C0,
            model_version=model,
        )
    ]
    for s in _attr(report, "surges") or []:
        fips = str(_attr(s, "fips"))
        values = {
            "onset": when(_utc(_attr(s, "onset_at"))),
            "detected": when(_utc(_attr(s, "detected_at"))),
            "customers_out": count(_attr(s, "customers_out") or 0),
            "peak_customers_out": count(_attr(s, "peak_customers_out") or 0),
            "baseline_customers_out": count(_attr(s, "baseline_customers_out") or 0),
            "share_out": share(float(_attr(s, "share_out") or 0.0)),
            "confidence": share(float(_attr(s, "confidence") or 0.0)),
        }
        flags = list(_attr(s, "dq_flags") or [])
        out.append(
            item(
                ctx,
                "outage_surge",
                f"Outage surge in {county_label(fips)}",
                citation,
                values=values,
                entity_ids=[str(_attr(s, "surge_id")), fips],
                classification=Classification.C0,
                model_version=model,
                hints=hints(
                    status=_attr(s, "status"),
                    confidence=_attr(s, "confidence_band"),
                    data_quality=flags[0] if flags else "ok",
                ),
            )
        )
    return out


async def get_damage_photos(args: dict[str, Any], ctx: ToolContext) -> list[EvidenceItem]:
    from sgw.api.scenario_phase import phase_at
    from sgw.models.cv.read import MAX_LIMIT

    if phase_at(getattr(ctx.reads, "scenario", "helene"), ctx.at) == "before_landfall":
        raise NotAvailable("no damage photos yet: field photos come in after landfall")

    queue = await ctx.reads.damage_queue(MAX_LIMIT)
    citation = f"{queue.model_id} triage scores; a reviewer confirms every photo"
    revision = f"{queue.model_id}@{queue.model_revision[:12]}"
    case_id, tier = args.get("case_id"), args.get("tier")
    cases = [c for c in queue.cases if (not case_id or c.case_id == case_id) and (not tier or c.tier == tier)]
    if case_id:
        members = {p for c in cases for p in c.photo_ids}
        photos = [p for p in queue.rows if p.image_id in members or p.seeded_case_id == case_id]
    else:
        photos = [p for p in queue.rows if not tier or p.tier == tier]
    out = [
        item(
            ctx,
            "damage_case",
            f"Damage case {c.case_id} on {c.section_id}, {c.damage_state} damage",
            citation,
            values={"case_score": share(c.case_score), "case_rank": count(c.case_rank)},
            entity_ids=[c.case_id, c.section_id],
            model_version=revision,
            hints=hints(tier=c.tier, status=c.status),
        )
        for c in cases[:MAX_ROWS]
    ]
    for p in photos[: args.get("limit") or 10]:
        out.append(
            item(
                ctx,
                "damage_photo",
                f"Damage photo {p.image_id}" + (f" on {p.section_id}" if p.section_id else ""),
                citation,
                values={"triage_score": share(p.triage_score), "queue_rank": count(p.rank)},
                entity_ids=[p.image_id, p.seeded_case_id, p.section_id],
                model_version=revision,
                hints=hints(tier=p.tier, status=p.status, top_signal=p.signals[0] if p.signals else None),
            )
        )
    return out


EXECUTORS: dict[str, Executor] = {
    "get_risk": get_risk,
    "get_forecast": get_forecast,
    "get_outages": get_outages,
    "get_crews": get_crews,
    "list_anomalies": list_anomalies,
    "get_feed_health": get_feed_health,
    "run_what_if": run_what_if,
    "list_decisions": list_decisions,
    "get_readiness": get_readiness,
    "get_etr": get_etr,
    "list_outage_surges": list_outage_surges,
    "get_damage_photos": get_damage_photos,
}
