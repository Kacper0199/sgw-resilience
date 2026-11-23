"""SC-5 ETR scorecard: P50 and bands of each published estimate against the WP-17 process's own simulated
restoration ("simulated actual, not the replay curve"), as K17 rows."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from sgw.contracts.eval_report import EvalReport
from sgw.models.restoration.etr import GLOBAL
from sgw.reports import scorecard as sc
from sgw.reports.sources import load_estimates

DATA = Path(__file__).resolve().parents[1] / "agent" / "graphs" / "data"
REPO = Path(__file__).resolve().parents[3]
COMMITTED = REPO / "data" / "artefacts" / "evals" / "etr_story_scorecard.json"


def test_score_checks_p50_error_and_bands_against_the_simulated_actual() -> None:
    est = load_estimates(DATA / "etr_story_h24.jsonl")
    g = next(e for e in est if e.scope == "global")
    actuals = {e.region_id: (e.hours_from_as_of["p50"] + 1.0, 40.0) for e in est}
    actuals[GLOBAL] = (g.hours_from_as_of["p90"] + 5.0, 70.0)
    scores = {s.region_id: s for s in sc.score(est, actuals)}
    glob = scores[GLOBAL]
    assert glob.actual_label == "simulated actual, not the replay curve"
    assert glob.in_p10_p90 is False and glob.in_p25_p75 is False
    assert glob.actual_utc == g.as_of_utc + timedelta(hours=g.hours_from_as_of["p90"] + 5.0)
    region = next(s for s in scores.values() if s.scope == "region")
    assert region.p50_error_h == -1.0 and region.abs_error_h == 1.0
    rows = {r.metric: r for r in sc.metric_rows(list(scores.values()))}
    r = rows["etr90.story_scorecard.region.p50_abs_error_h_median"]
    assert r.n == 11 and r.split.value == "dev" and r.label.value == "S" and r.value == 1.0
    assert "simulated actual, not the replay curve" in r.baseline_name


def test_committed_scorecard_reproduces_from_the_wp17_story_run() -> None:
    committed = json.loads(COMMITTED.read_text(encoding="utf-8"))
    EvalReport.model_validate({k: v for k, v in committed.items() if k not in ("actual_label", "estimates")})
    est = load_estimates(DATA / "etr_story_h24.jsonl")
    doc, scores = sc.report(est, committed["command"])
    assert [m.model_dump(mode="json") for m in doc.metrics] == committed["metrics"]
    assert [s.model_dump(mode="json") for s in scores] == committed["estimates"]
    assert committed["actual_label"] == sc.ACTUAL_LABEL


def test_story_actuals_are_computed_once_per_process_and_issue_time() -> None:
    """G1: `GET /api/after-action` took about 12 s live because every read re-ran the ETR story simulation.
    The run is deterministic, so it is cached (and warmed at API start); a repeat read is milliseconds."""
    import time

    est = load_estimates(DATA / "etr_story_h24.jsonl")
    first = sc.simulated_actuals(est)
    started = time.perf_counter()
    again = sc.simulated_actuals(est)
    assert time.perf_counter() - started < 0.5
    assert again == first and again is not first
    assert sc._story.cache_info().currsize == 1
    later = [e.model_copy(update={"as_of_utc": e.as_of_utc + timedelta(hours=6)}) for e in est]
    started = time.perf_counter()
    assert sc.simulated_actuals(later) != first
    assert time.perf_counter() - started < 1.0


def test_a_revision_that_keeps_restored_areas_is_scored_at_each_issue_time() -> None:
    """V6-05: a published revision re-issues the global and the areas still restoring and keeps the estimates
    of areas already restored, so one publication holds two issue times; the after-action read scored it with
    one issue time and failed (500)."""
    est = load_estimates(DATA / "etr_story_h24.jsonl")
    later = est[0].as_of_utc + timedelta(hours=6)
    mixed = [e.model_copy(update={"as_of_utc": later}) if e.scope == "global" else e for e in est]
    scores = sc.score_publication(mixed)
    assert [s.region_id for s in scores] == [s.region_id for s in sc.score(est, sc.simulated_actuals(est))]
    regions = [e for e in est if e.scope == "region"]
    assert [s for s in scores if s.scope == "region"] == sc.score(regions, sc.simulated_actuals(regions))
    glob = next(s for s in scores if s.scope == "global")
    assert glob.as_of_utc == later
    assert sc.score_publication(est) == sc.score(est, sc.simulated_actuals(est))
