"""Blue-sky baseline (S-BLUE week 2024-05-06..12 Eastern): nothing fires, and the Readiness queue carries the
work. Outputs: an empty `weather.jsonl` (no alert: the true negative, F1), `eam.jsonl` with the open work
order behind each Readiness case, `readiness_cases.json` (K16 cases, waterfalls, critical path) and
`baseline.json` (both triggers over the window and over the whole station record, so the alarm rate is on
the table)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sgw.generator.scenarios import common as cm
from sgw.generator.scenarios import fireweather as fwm
from sgw.generator.scenarios import heat as heat_sc
from sgw.generator.scenarios import readiness as rd
from sgw.generator.scenarios.weather import EASTERN, GSP_HOURLY, STATIONS_DAILY
from sgw.generator.wind import epoch
from sgw.models.clocks.waterfall import TermKind

SCENARIO = "bluesky"
WINDOW = (datetime(2024, 5, 6, 4, tzinfo=UTC), datetime(2024, 5, 13, 4, tzinfo=UTC))


def _row(row: Any) -> dict[str, Any]:
    return {
        "label": row.label,
        "basis_id": row.basis.basis_id if row.basis else None,
        "term_kind": TermKind(row.term_kind).value,
        "unit": row.unit,
        "p10": row.p10,
        "p50": row.p50,
        "p90": row.p90,
    }


def readiness_payload(now: datetime = rd.NOW) -> dict[str, Any]:
    q = rd.queue(now=now)
    seeds = {s.case_id: s for s in rd.SEEDS}
    cases = []
    for cid in sorted(q.cases, key=lambda c: (q.cases[c].case.effective_decide_by_utc, c)):
        c = q.cases[cid]
        hours_left = (c.case.effective_decide_by_utc - now).total_seconds() / 3600.0
        cases.append(
            {
                "case": c.case.model_dump(mode="json"),
                "waterfall": c.waterfall().model_dump(mode="json"),
                "waterfall_rows": [_row(x) for x in c.waterfall_rows()],
                "missed": c.missed,
                "hours_to_effective_decide_by": cm.r(hours_left, 1),
                "slack_min": c.path.slack_min,
                "binding_chain": list(c.path.binding_chain),
                "asset_id": seeds[cid].asset_id,
                "work_type": seeds[cid].work_type,
                "priority": seeds[cid].priority,
            }
        )
    return {
        "mode": "readiness",
        "label": "synthetic",
        "scenario_now_utc": cm.iso(now),
        "season_deadline_utc": cm.iso(rd.SEASON_DEADLINE),
        "clock_service": "WP-12 compute_queue (lead times from the WP-12 registry)",
        "budget_cut_keeps": [s.case_id for s in sorted(rd.SEEDS, key=lambda s: s.priority)[:3]],
        "cases": cases,
    }


def baseline_payload() -> dict[str, Any]:
    fw = fwm.gsp()
    window_fire = [e for e in fw.trigger.episodes if WINDOW[0] <= e.start_utc < WINDOW[1]]
    window_hours = [h for h in fw.trigger.hours if WINDOW[0] <= h.t < WINDOW[1]]
    trig = heat_sc.trigger()
    first, last = (t.astimezone(EASTERN).date() for t in (WINDOW[0], WINDOW[1] - timedelta(hours=1)))
    ffwi_days = sorted({h.t.astimezone(EASTERN).date() for h in fw.trigger.hours if h.ffwi_branch})
    kbdi_days = sorted({h.t.astimezone(EASTERN).date() for h in fw.trigger.hours if h.kbdi_branch})
    record_days = len({h.t.astimezone(EASTERN).date() for h in fw.trigger.hours})

    def years(days: list[date]) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in days:
            out[str(d.year)] = out.get(str(d.year), 0) + 1
        return out

    return {
        "scenario": SCENARIO,
        "window_utc": [cm.iso(WINDOW[0]), cm.iso(WINDOW[1])],
        "wildfire": {
            "rule_id": fw.trigger.rule.rule_id,
            "fired_in_window": bool(window_fire),
            "window_ffwi_max": cm.r(max(h.ffwi for h in window_hours), 1),
            "window_rh_min_pct": cm.r(min(h.rh_pct for h in window_hours), 1),
            "window_kbdi_max": cm.r(max(h.kbdi or 0.0 for h in window_hours), 1),
            "record": {
                "station": "GSP",
                "days": record_days,
                "ffwi_rh_branch_days": len(ffwi_days),
                "ffwi_rh_branch_days_by_year": years(ffwi_days),
                "kbdi_branch_days": len(kbdi_days),
                "kbdi_branch_days_by_year": years(kbdi_days),
                "episodes": len(fw.trigger.episodes),
            },
        },
        "heat": {
            "threshold_c": cm.r(trig.threshold_c, 2),
            "fired_in_window": bool(trig.fires_in(first, last)),
            "hot_days_in_window": [d.isoformat() for d in trig.hot_days if first <= d <= last],
            "record_fire_days": [d.isoformat() for d in trig.fire_days],
        },
    }


def build(out: Path) -> dict[str, Any]:
    payload = readiness_payload()
    s = cm.sink(SCENARIO, *WINDOW)
    for i, c in enumerate(payload["cases"]):
        cid = c["case"]["decision_case_id"]
        s.add(
            "WorkOrder",
            epoch(WINDOW[0]) + 3600.0 * (2 + i),
            {
                "work_order_id": f"WO-{cid.removeprefix('DC-')}",
                "status": "open",
                "asset_id": c["asset_id"],
                "work_type": c["work_type"],
                "crew_id": None,
                "proposal_id": None,
            },
            key=f"wo-{cid}",
            source="eam",
            region=rd.REGION,
            domain=c["case"]["domain"],
        )
    for feed in ("eam", "weather"):
        cm.write_feed(
            out,
            SCENARIO,
            feed,
            s.by_feed.get(feed, []),
            *WINDOW,
            calibration_source="Readiness seeds per D-022/O-07; clocks via WP-12 compute_queue",
            note="Generated by `uv run python -m sgw.generator.scenarios generate bluesky`. Synthetic.",
            data_label="synthetic",
        )
    cm.write_json(out / "readiness_cases.json", payload)
    base = baseline_payload()
    cm.write_json(out / "baseline.json", base)
    outputs = ["eam.jsonl", "weather.jsonl", "readiness_cases.json", "baseline.json"]
    cm.write_manifest(out, SCENARIO, outputs, [GSP_HOURLY, STATIONS_DAILY, rd.LEAD_TIMES_PATH])
    return {"readiness": payload, "baseline": base}
