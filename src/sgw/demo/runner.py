"""`sgw demo smoke` and `sgw demo build`: the PS-17 story on a private host stack (replay gateway, OPA, API).

smoke  a scratch database seeded like `sgw seed --demo`, the ten story steps with model-provenance asserts,
       the replay hit rate from the gateway's counters (any miss fails), then K19 playback with the
       gateway stopped; writes `out/demo-smoke.json`; exit status = failures.
build  a build database seeded with the stack's demo passwords, the same steps, a template database per
       bookmark and an event log per bookmark under `data/fixtures/eventlog/`."""

from __future__ import annotations

import json
import secrets
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sgw.demo import eventlog, snapshots
from sgw.demo.bookmarks import REVIEW_TIME, Bookmark, bookmark
from sgw.demo.client import Run
from sgw.demo.harness import REPO, DemoStack, policy_opa, tail
from sgw.demo.story import STEPS, StepResult, Story, run_story

SMOKE_OUT = REPO / "out" / "demo-smoke.json"


def _graph_version(graph: str) -> str:
    from sgw.agent.nodes.run_store import GRAPH_VERSIONS

    return GRAPH_VERSIONS.get(graph, f"{graph}@1")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@contextmanager
def _stack(runtime_url: str, workdir: Path) -> Iterator[DemoStack]:
    with policy_opa() as opa_url:
        stack = DemoStack(runtime_url, opa_url, workdir)
        try:
            stack.start_gateway()
            stack.start_api()
            yield stack
        finally:
            stack.close()


@dataclass
class ReplayRate:
    hits: int
    misses: int

    @property
    def rate(self) -> float | None:
        total = self.hits + self.misses
        return None if total == 0 else round(self.hits / total, 4)


def _replay(before: dict[str, int], after: dict[str, int]) -> ReplayRate:
    return ReplayRate(
        after.get("replay_hits", 0) - before.get("replay_hits", 0),
        after.get("replay_misses", 0) - before.get("replay_misses", 0),
    )


def playback_check(stack: DemoStack, story: Story, admin_url: str, database: str) -> dict[str, Any]:
    """Mark the database at bookmark after-action (what `goto` does), stop this stack's own gateway and start
    the after-action run at the review time: the recorded run must stream with the replay banner and end
    like the recording. The mark is removed again."""
    import psycopg

    bm = bookmark("after-action")
    if bm.run_graph is None or bm.run_module is None:
        return {"ok": False, "detail": f"bookmark {bm.id} has no key run"}
    at = datetime.fromisoformat(REVIEW_TIME.replace("Z", "+00:00"))
    log = eventlog.match(bm.run_graph, at, bm.id, _graph_version(bm.run_graph), run_input=bm.run_input)
    if log is None:
        return {"ok": False, "detail": f"no event log for {bm.id} in {eventlog.eventlog_dir()}"}
    with psycopg.connect(admin_url, autocommit=True) as conn:
        snapshots.mark(conn, database, bm.id)
    stack.stop("gateway")
    try:
        run = story.p("ic_01").run(bm.run_graph, bm.run_input, bm.run_module)
    finally:
        stack.start_gateway()
        with psycopg.connect(admin_url, autocommit=True) as conn:
            snapshots.mark(conn, database, None)
    banner = (run.frames[0].get("payload") or {}).get("playback") if run.frames else None
    recorded = [ln.frame.type.value for ln in log.lines]
    played = [f["type"] for f in run.frames]
    ok = bool(banner) and played == recorded and run.last["run_id"] == run.run_id
    return {
        "ok": ok,
        "bookmark": log.header.bookmark,
        "source_run_id": log.header.source_run_id,
        "frames": len(played),
        "banner": bool(banner),
        "detail": "" if ok else f"played {played[:6]}.. vs recorded {recorded[:6]}..; banner={bool(banner)}",
    }


def _smoke_run(report: dict[str, Any], playback: bool) -> int:
    from sgw.approval.demo_seed import seed_demo
    from sgw.ingest.testing import scratch_database

    failures = 0
    password = "smoke-" + secrets.token_hex(12)
    with tempfile.TemporaryDirectory(prefix="sgw-demo-smoke-") as tmp, scratch_database("demo") as db:
        t0 = time.perf_counter()
        seed_demo(db.admin_url, password)
        report["seed_seconds"] = round(time.perf_counter() - t0, 1)
        workdir = Path(tmp)
        try:
            with _stack(db.runtime_url, workdir) as stack:
                story = Story(stack.base, lambda _user: password)
                try:
                    before = stack.gateway_counters()
                    results = run_story(story)
                    rate = _replay(before, stack.gateway_counters())
                    report["steps"] = [asdict(r) for r in results]
                    report["replay"] = {"hits": rate.hits, "misses": rate.misses, "hit_rate": rate.rate}
                    failures += sum(1 for r in results if not r.ok) + (len(results) < len(STEPS))
                    failures += int(rate.misses > 0 or rate.hits == 0)
                    if playback and failures == 0:
                        report["playback"] = playback_check(stack, story, db.admin_url, db.name)
                        failures += int(not report["playback"]["ok"])
                finally:
                    story.close()
        except Exception:
            report["api_log"] = tail(workdir / "api.log")
            raise
    return failures


def smoke(out: Path = SMOKE_OUT, playback: bool = True) -> int:
    """Never raises: any exception is one failure in the report. A stale report is removed first."""
    out.unlink(missing_ok=True)
    started = time.perf_counter()
    report: dict[str, Any] = {"started_at": _now(), "steps": [], "ok": False}
    try:
        failures = _smoke_run(report, playback)
    except Exception as exc:  # noqa: BLE001 - the smoke reports every failure, it never crashes
        report["error"] = f"{type(exc).__name__}: {exc}"[:2000]
        failures = 1 + sum(1 for s in report["steps"] if not s["ok"])
    report["ok"] = failures == 0
    report["failures"] = failures
    report["seconds"] = round(time.perf_counter() - started, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return failures


@dataclass
class BuildHooks:
    stack: DemoStack
    admin_url: str
    database: str
    capture_dir: Path | None
    timings: dict[str, float] = field(default_factory=dict)
    captured: dict[str, str] = field(default_factory=dict)

    def bookmark(self, story: Story, bm: Bookmark) -> None:
        self.stack.stop("api")
        self.timings[bm.id] = round(snapshots.snapshot(self.admin_url, self.database, bm), 2)
        self.stack.start_api()
        story.relogin()

    def key_run(self, story: Story, bm: Bookmark, run: Run) -> None:
        if self.capture_dir is None or bm.run_graph is None:
            return
        path, _ = eventlog.capture(
            bm, run.run_id, _graph_version(bm.run_graph), run.frames, run.ids, run.gaps_ms, self.capture_dir
        )
        self.captured[bm.id] = str(path.relative_to(REPO) if path.is_relative_to(REPO) else path)


@dataclass
class BuildReport:
    database: str
    steps: list[StepResult]
    snapshot_seconds: dict[str, float]
    eventlogs: dict[str, str]
    seed_seconds: float
    seconds: float
    replay: ReplayRate

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps) and len(self.steps) == len(STEPS) and self.replay.misses == 0


def build(
    database: str,
    password_for: Callable[[str], str],
    seed: Callable[[str], None],
    capture_dir: Path | None = eventlog.EVENTLOG_DIR,
) -> BuildReport:
    """Recreate `database`, seed it, drive the story and snapshot each bookmark. Never the demo database."""
    from sgw.cli.commands.database import apply_migrations
    from sgw.cli.support import load_credentials

    if database == "sgw":
        raise ValueError("build into a separate database; `sgw demo goto` copies a bookmark into sgw")
    creds = load_credentials()
    admin = creds.admin_dsn()
    started = time.perf_counter()
    import psycopg
    from psycopg import sql

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
    apply_migrations(database=database, create=True)
    t0 = time.perf_counter()
    seed(creds.owner_dsn(database))
    seed_seconds = round(time.perf_counter() - t0, 1)
    with (
        tempfile.TemporaryDirectory(prefix="sgw-demo-build-") as tmp,
        _stack(creds.runtime_dsn(database), Path(tmp)) as stack,
    ):
        hooks = BuildHooks(stack, admin, database, capture_dir)
        story = Story(stack.base, password_for, hooks=hooks)
        before = stack.gateway_counters()
        try:
            results = run_story(story)
        finally:
            story.close()
        rate = _replay(before, stack.gateway_counters())
    return BuildReport(
        database,
        results,
        hooks.timings,
        hooks.captured,
        seed_seconds,
        round(time.perf_counter() - started, 1),
        rate,
    )


def built(admin_url: str) -> dict[str, bool]:
    from sgw.demo.bookmarks import BOOKMARKS

    return {b.id: snapshots.exists(admin_url, b.template) for b in BOOKMARKS}


__all__ = ["bookmark", "build", "built", "smoke"]
