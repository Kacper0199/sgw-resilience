"""Ask bank runner: asks every selected item through a private SGW API as its persona at its demo moment,
grades the answer with the code graders and writes a JSON + Markdown report.

The private stack (never the shared :8080): OPA from the test harness, an LLM gateway in the given mode on
the shared spend ledger (so the 40 USD soft stop and the daily cap apply; LLM_BUDGET_ACK only with
`--budget-ack`), its own wave cap = the wave's booked spend at start + `--cap-usd`, and the API (DEMO_MODE,
zone rules, SGW_DB_POOL_MAX=2) on an eval database copied from the demo template. Each moment is loaded with
POST /api/demo/goto; prior turns of a follow-up are asked first in the same thread.

  uv run python -m sgw.evals.ask_bank.run --split dev --smoke --label c1-smoke
  uv run python -m sgw.evals.ask_bank.run --split all --sample 60 --label baseline-main
  uv run python -m sgw.evals.ask_bank.run --api http://127.0.0.1:63510 --gateway http://127.0.0.1:63511 ...

Live calls carry x-sgw-purpose=eval and x-sgw-wave=<wave> (SGW_LLM_PURPOSE / SGW_LLM_WAVE on the API).
Secrets are read by name from var/ and .env and never printed."""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import random
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from sgw.evals.ask_bank import graders, report
from sgw.evals.ask_bank.schema import REPO, Item, load, smoke_ids

OUT = REPO / "data" / "artefacts" / "evals" / "ask_bank"
EVAL_DB = "sgw_wp33_c2_eval"
API_PORT, GATEWAY_PORT = 63510, 63511
MOMENT_ORDER = ("at-n1", "morning-after", "notices-lifted")
PRESENTER = "ic_01"


def state_paths() -> dict[str, Path]:
    from sgw.cli.support import secrets_dir, var_dir

    return {
        "host_env": secrets_dir() / "host.env",
        "ledger": var_dir() / "llm" / "llm_spend.csv",
        "live_cache": var_dir() / "llm" / "live_cache",
    }


def admin_dsn() -> str:
    from sgw.cli.support import read_env_file

    return read_env_file(state_paths()["host_env"])["SGW_ADMIN_DATABASE_URL"].strip().strip('"')


def dsn(db: str) -> str:
    return admin_dsn().rsplit("/", 1)[0] + "/" + db


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def ledger_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def wave_spend(path: Path, wave: str) -> float:
    return sum(float(r.get("cost_usd") or 0) for r in ledger_rows(path) if r.get("wave") == wave)


def run_costs(path: Path, run_ids: set[str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = defaultdict(lambda: {"usd": 0.0, "live_calls": 0.0})
    for r in ledger_rows(path):
        if r.get("run_id") in run_ids:
            out[r["run_id"]]["usd"] += float(r.get("cost_usd") or 0)
            out[r["run_id"]]["live_calls"] += 1
    return out


def select(args: argparse.Namespace) -> list[Item]:
    items = load(args.split)
    if args.smoke:
        wanted = smoke_ids()
        by_id = {i.id: i for i in items}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            raise SystemExit(f"smoke ids not in split {args.split}: {missing}")
        items = [by_id[i] for i in wanted]
    if args.no_smoke:
        skip = set(smoke_ids())
        items = [i for i in items if i.id not in skip]
    if args.ids:
        wanted_ids = set(args.ids.split(","))
        items = [i for i in items if i.id in wanted_ids]
    if args.klass:
        items = [i for i in items if i.klass in set(args.klass.split(","))]
    if args.sample:
        items = stratified(items, args.sample, seed=args.seed)
    return items


def stratified(items: Sequence[Item], n: int, seed: int = 33) -> list[Item]:
    """About n items, every class x language stratum represented, the rest proportional (seeded)."""
    strata: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for i in sorted(items, key=lambda i: i.id):
        strata[(i.klass, i.lang)].append(i)
    rng = random.Random(seed)  # noqa: S311 - a reproducible sample, not a secret
    for group in strata.values():
        rng.shuffle(group)
    picked = [g.pop() for g in strata.values()]
    rest = [i for g in strata.values() for i in g]
    rng.shuffle(rest)
    picked += rest[: max(0, n - len(picked))]
    return sorted(picked, key=lambda i: i.id)


@dataclass
class Outcome:
    item: Item
    answer: dict[str, Any] | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    error: str | None = None
    grade: dict[str, Any] = field(default_factory=dict)
    usd: float = 0.0
    live_calls: int = 0

    def row(self) -> dict[str, Any]:
        a = self.answer or {}
        ans = graders.Answer.of(a)
        return {
            **self.item.model_dump(),
            "split": self.item.split,
            "pass": bool(self.grade.get("pass")),
            "failed": self.grade.get("failed", []),
            "checks": self.grade.get("checks", {}),
            "info": self.grade.get("info", {}),
            "error": self.error,
            "path": a.get("path"),
            "reason": a.get("reason"),
            "text": a.get("text"),
            "links": [{"page": link.page, "href": link.href} for link in ans.links()],
            "photos": len(ans.photos()),
            "suggestions": ans.suggestions()[:6],
            "language_detected": graders.language(ans.text),
            "prior_answers": [t.get("text") for t in self.turns],
            "answer": a,
            "run_ids": self.run_ids,
            "latency_s": round(self.latency_s, 2),
            "usd": round(self.usd, 5),
            "live_calls": self.live_calls,
        }


class Asker:
    """One logged-in session per (worker thread, persona); a chain shares one thread (conversation)."""

    def __init__(self, base: str) -> None:
        from sgw.cli.support import load_demo_env

        self.base = base
        self.env = load_demo_env()
        self.local = threading.local()

    def persona(self, user: str) -> Any:
        from sgw.contracts.identities import demo_password_for
        from sgw.demo.client import Persona

        cache: dict[str, Any] = self.local.__dict__.setdefault("sessions", {})
        if user not in cache:
            cache[user] = Persona(self.base, user, demo_password_for(user, self.env) or "", timeout_s=240)
        return cache[user]

    def close(self) -> None:
        for p in getattr(self.local, "sessions", {}).values():
            p.close()
        self.local.__dict__.pop("sessions", None)

    def ask(self, item: Item) -> Outcome:
        from sgw.demo.client import Run

        out = Outcome(item)
        started = time.monotonic()
        try:
            p = self.persona(item.persona)
            t = p.post("/api/threads", {"module": "ask"})
            if t.status_code == 403:
                code = (t.json().get("error") or {}).get("code") if t.content else None
                raise PermissionError(f"role_blocked: POST /api/threads HTTP 403 {code}")
            if t.status_code != 201:
                raise RuntimeError(f"thread: HTTP {t.status_code}")
            thread_id = t.json()["thread_id"]
            for question in [*item.turns, item.question]:
                body: dict[str, Any] = {"question": question}
                r = p.post(f"/api/threads/{thread_id}/runs", {"graph": "copilot", "input": body})
                if r.status_code != 202:
                    raise RuntimeError(f"run: HTTP {r.status_code} {r.text[:160]}")
                run = Run(thread_id=thread_id, run_id=r.json()["run_id"])
                p.frames(run, timeout_s=240)
                out.run_ids.append(run.run_id)
                said = [a for a in run.artifacts("message") if a.get("role") == "assistant"]
                if not said:
                    raise RuntimeError(f"no answer ({run.status})")
                out.turns.append(said[-1])
            out.answer = out.turns.pop()
        except Exception as exc:  # noqa: BLE001 - one item's failure is recorded, the run goes on
            out.error = f"{type(exc).__name__}: {exc}"[:300]
        out.latency_s = time.monotonic() - started
        out.grade = graders.grade(item, graders.Answer.of(out.answer))
        if out.error:
            out.grade = {**out.grade, "pass": False, "failed": sorted({*out.grade["failed"], "error"})}
        return out


def goto(base: str, moment: str, asker: Asker) -> float:
    p = asker.persona(PRESENTER)
    for attempt in range(5):
        r = p.post("/api/demo/goto", {"bookmark": moment})
        if r.status_code == 200:
            return float(r.json().get("seconds") or 0)
        time.sleep(3 + 3 * attempt)
    raise RuntimeError(f"goto {moment}: HTTP {r.status_code} {r.text[:200]}")


def counters(gateway: str | None) -> dict[str, int]:
    if not gateway:
        return {}
    try:
        r = httpx.get(f"{gateway}/healthz", timeout=5)
        return {k: int(v) for k, v in dict(r.json().get("counters") or {}).items()}
    except (httpx.HTTPError, ValueError):
        return {}


@contextlib.contextmanager
def private_stack(args: argparse.Namespace, workdir: Path) -> Iterator[tuple[str, str, str | None]]:
    from sgw.demo import harness
    from sgw.demo.bookmarks import bookmark
    from sgw.demo.harness import DemoStack, clean_env, policy_opa, wait_ok
    from sgw.demo.snapshots import goto as copy_template

    paths = state_paths()
    token, cli_token = secrets.token_hex(24), secrets.token_hex(24)
    copy_template(admin_dsn(), bookmark(MOMENT_ORDER[0]), args.db)
    gw_env = {
        **clean_env(),
        "LLM_MODE": args.gateway_mode,
        "LLM_EGRESS_PDP": "reference",
        "LLM_SPEND_CSV": str(paths["ledger"]),
        "LLM_LIVE_CACHE_DIR": str(paths["live_cache"]),
        "LLM_CALLER_TOKEN_SHA256": f"api:{digest(token)},cli:{digest(cli_token)}",
        "LLM_WAVE_CAP_USD": f"{wave_spend(paths['ledger'], args.wave) + args.cap_usd:.4f}",
        "LLM_REPLAY_PACE_MAX_S": str(args.pace),
        **({"LLM_BUDGET_ACK": str(args.budget_ack)} if args.budget_ack else {}),
    }
    if args.gateway_mode != "replay":
        from sgw.cli.support import llm_env_file, read_env_file

        key = read_env_file(llm_env_file()).get("ANTHROPIC_API_KEY", "").strip().strip('"')
        if not key:
            raise SystemExit("no API key in the gateway key file: live modes need one")
        gw_env["ANTHROPIC_API_KEY"] = key
    code = args.code_root.resolve() if args.code_root else REPO
    code_env = {"PYTHONPATH": f"{code / 'src'}{os.pathsep}{code}"} if args.code_root else {}
    gw_env |= code_env
    harness.REPO = code
    gw_cmd = [sys.executable, "-m", "uvicorn", "services.llm_gateway.api:create_app", "--factory"]
    gw_cmd += ["--host", "127.0.0.1", "--port", str(args.gateway_port), "--log-level", "warning"]
    gateway = f"http://127.0.0.1:{args.gateway_port}"
    with policy_opa() as opa, (workdir / "gateway.log").open("ab") as gw_log:
        gw = subprocess.Popen(gw_cmd, env=gw_env, stdout=gw_log, stderr=subprocess.STDOUT, cwd=code)  # noqa: S603
        stack = DemoStack(dsn(args.db), opa, workdir, gateway_url_override=gateway, api_port=args.api_port)
        try:
            wait_ok(f"{gateway}/healthz")
            stack.start_api(
                {
                    "SGW_DEMO_GOTO_DSN": admin_dsn(),
                    "SGW_DB_POOL_MAX": str(args.pool),
                    "SGW_GATEWAY_TOKEN": token,
                    "SGW_LLM_PURPOSE": "eval",
                    "SGW_LLM_WAVE": args.wave,
                    **code_env,
                    **({"SGW_DEMO_TEMPLATE_PREFIX": args.template_prefix} if args.template_prefix else {}),
                    **({"SGW_SCENARIO_INJECTS": "1"} if args.injects else {}),
                }
            )
            yield stack.base, gateway, cli_token
        finally:
            stack.close()
            gw.terminate()
            try:
                gw.wait(timeout=15)
            except subprocess.TimeoutExpired:
                gw.kill()


def execute(items: list[Item], base: str, gateway: str | None, workers: int) -> list[Outcome]:
    asker_by_moment: list[Outcome] = []
    asker = Asker(base)
    try:
        for moment in MOMENT_ORDER:
            mine = [i for i in items if i.moment == moment]
            if not mine:
                continue
            secs = goto(base, moment, asker)
            asker.close()
            print(f"moment {moment}: loaded in {secs:.1f}s, {len(mine)} items", flush=True)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for out in pool.map(asker.ask, mine):
                    mark = "PASS" if out.grade["pass"] else "FAIL"
                    print(
                        f"{mark} {out.item.id:<14} {out.latency_s:5.1f}s {','.join(out.grade['failed'])}",
                        flush=True,
                    )
                    asker_by_moment.append(out)
    finally:
        asker.close()
    return asker_by_moment


def stored_answer(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The raw answer of a stored row; rows written before the raw payload was kept are rebuilt from their
    text, path, reason, links and photo count (enough for every grader)."""
    if "answer" in row:
        return row["answer"] or None
    if row.get("error") and not row.get("text"):
        return None
    refs = [{"kind": "photo", "id": f"photo-{n}"} for n in range(int(row.get("photos") or 0))]
    return {
        "text": row.get("text") or "",
        "path": row.get("path"),
        "reason": row.get("reason"),
        "links": row.get("links") or [],
        "references": refs,
        "write_attempts": 0,
    }


def regrade_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_id = {i.id: i for i in load("all")}
    out = []
    for r in rows:
        item = by_id.get(r["id"])
        if item is None:
            continue
        error = r.get("error")
        if error and "thread: HTTP 403" in error:
            error = "PermissionError: role_blocked: POST /api/threads HTTP 403 (row before R33 error codes)"
        o = Outcome(item, answer=stored_answer(r), run_ids=r.get("run_ids") or [], error=error)
        o.turns = [{"text": t} for t in r.get("prior_answers") or []]
        o.latency_s, o.usd, o.live_calls = float(r["latency_s"]), float(r["usd"]), int(r["live_calls"])
        o.grade = graders.grade(item, graders.Answer.of(o.answer))
        if o.error:
            o.grade = {**o.grade, "pass": False, "failed": sorted({*o.grade["failed"], "error"})}
        out.append(o.row())
    return out


def private_copy(path: Path) -> Path:
    """The full report (held-out rows unredacted) when one was written outside git."""
    full = report.private_dir() / path.name
    return full if full.is_file() else path


def regrade(paths: Sequence[Path], out: Path, label: str) -> Path:
    """Grade stored reports again with the current graders; with several, a later report's row replaces an
    earlier one with the same id (a re-ask of infra misses). Asks nothing."""
    reports = [json.loads(private_copy(p).read_text(encoding="utf-8")) for p in paths]
    merged: dict[str, Mapping[str, Any]] = {}
    for rep in reports:
        merged |= {r["id"]: r for r in rep["items"]}
    usd = sum(float(r.get("usd") or 0) for rep in reports for r in rep["items"])
    meta = {**reports[0]["meta"], "label": label, "regraded_from": [p.name for p in paths]}
    data = report.build(meta, regrade_rows(list(merged.values())))
    data["summary"]["usd_all_runs"] = round(usd, 4)
    judged = [rep["judge"] for rep in reports if rep.get("judge")]
    if judged:
        data["judge"] = judged[-1]
        data["summary"]["judge_pass_rate"] = judged[-1]["pass_rate"]
    return report.write(data, out, label)[0]


def serve(args: argparse.Namespace) -> int:
    """A private stack for checks by hand (browser, curl): held until the stop file appears."""
    with tempfile.TemporaryDirectory(prefix="sgw-askbank-") as tmp, private_stack(args, Path(tmp)) as stack:
        base, gateway, _ = stack
        print(f"api {base} gateway {gateway} logs {tmp}", flush=True)
        while not args.serve.exists():
            time.sleep(1)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev", choices=["dev", "heldout", "all"])
    ap.add_argument("--smoke", action="store_true", help="only the 40 smoke ids (dev)")
    ap.add_argument("--ids", help="comma-separated item ids")
    ap.add_argument("--no-smoke", action="store_true", help="leave out the smoke ids")
    ap.add_argument("--klass", help="comma-separated classes")
    ap.add_argument("--sample", type=int, help="stratified sample of about N items (class x language)")
    ap.add_argument("--seed", type=int, default=33)
    ap.add_argument("--label", help="report name under data/artefacts/evals/ask_bank/")
    ap.add_argument("--regrade", type=Path, nargs="+", help="grade stored report JSONs again (merged by id)")
    ap.add_argument("--api", help="use this running private API instead of starting one")
    ap.add_argument("--gateway", help="gateway URL of --api (for counters)")
    ap.add_argument(
        "--gateway-mode", default="replay_then_live", choices=["replay", "replay_then_live", "live"]
    )
    ap.add_argument("--wave", default="R33")
    ap.add_argument("--cap-usd", type=float, default=1.0, help="this run's live spend cap")
    ap.add_argument("--db", default=EVAL_DB)
    ap.add_argument("--template-prefix", help="SGW_DEMO_TEMPLATE_PREFIX for private templates")
    ap.add_argument("--api-port", type=int, default=API_PORT)
    ap.add_argument("--gateway-port", type=int, default=GATEWAY_PORT)
    ap.add_argument("--workers", type=int, default=1, help="parallel askers; keep 1 with pool 2")
    ap.add_argument("--pool", type=int, default=2, help="SGW_DB_POOL_MAX of the private API")
    ap.add_argument("--judge", type=int, default=0, help="LLM-judge N sampled answers (informative)")
    ap.add_argument(
        "--code-root", type=Path, help="run the API and gateway from this checkout (another branch)"
    )
    ap.add_argument("--budget-ack", type=float, help="LLM_BUDGET_ACK: the user's raised soft stop (USD)")
    ap.add_argument("--injects", action="store_true", help="exercise injects on (SGW_SCENARIO_INJECTS=1)")
    ap.add_argument("--pace", type=float, default=0.0, help="LLM_REPLAY_PACE_MAX_S of the private gateway")
    ap.add_argument("--serve", type=Path, help="hold the private stack until this file exists")
    ap.add_argument("--commit", default=os.environ.get("SGW_EVAL_COMMIT", ""))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if not args.label:
        raise SystemExit("--label is required")
    if args.regrade:
        print(regrade(args.regrade, args.out, args.label))
        return 0
    if args.serve:
        return serve(args)
    if args.split == "heldout" and args.smoke:
        raise SystemExit("the smoke subset is dev only")
    items = select(args)
    if not items:
        raise SystemExit("no items selected")
    code_repo = args.code_root or REPO
    commit = (
        args.commit
        or subprocess.run(  # noqa: S603
            ["git", "-C", str(code_repo), "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,  # noqa: S607
        ).stdout.strip()
    )
    print(
        f"{len(items)} items, split {args.split}, commit {commit}, gateway mode {args.gateway_mode}",
        flush=True,
    )
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="sgw-askbank-") as tmp:
        workdir = Path(tmp)
        external: tuple[str, str, str | None] = (args.api, args.gateway, None)
        stack = contextlib.nullcontext(external) if args.api else private_stack(args, workdir)
        try:
            with stack as (base, gateway, cli_token):
                before = counters(gateway)
                outcomes = execute(items, base, gateway, args.workers)
                after = counters(gateway)
                verdicts = None
                if args.judge and gateway and cli_token:
                    from sgw.evals.ask_bank import judge

                    verdicts = judge.run(
                        [o.row() for o in outcomes], args.judge, gateway, cli_token, args.wave
                    )
                    print(f"judge: {verdicts['scored']}/{verdicts['n']} scored, pass {verdicts['pass_rate']}")
        except Exception:
            for name in ("gateway.log", "api.log"):
                log = workdir / name
                if log.is_file():
                    tail = log.read_text(errors="replace").splitlines()[-12:]
                    print(
                        f"--- {name}\n" + "\n".join(t for t in tail if "postgres" not in t), file=sys.stderr
                    )
            raise
    costs = run_costs(state_paths()["ledger"], {r for o in outcomes for r in o.run_ids})
    for o in outcomes:
        o.usd = sum(costs[r]["usd"] for r in o.run_ids if r in costs)
        o.live_calls = int(sum(costs[r]["live_calls"] for r in o.run_ids if r in costs))
    meta = {
        "label": args.label,
        "commit": commit,
        "split": args.split,
        "smoke": args.smoke,
        "gateway_mode": args.gateway_mode,
        "wave": args.wave,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "seconds": round(time.time() - started, 1),
        "gateway_counters_delta": {k: after.get(k, 0) - before.get(k, 0) for k in after},
    }
    data = report.build(meta, [o.row() for o in outcomes])
    if verdicts:
        data["judge"] = verdicts
        data["summary"]["judge_pass_rate"] = verdicts["pass_rate"]
        data["summary"]["usd"] = round(data["summary"]["usd"] + verdicts["usd"], 4)
    paths = report.write(data, args.out, args.label)
    s = data["summary"]
    print(
        f"pass {s['passed']}/{s['n']} = {s['pass_rate']:.2f}; spend {s['usd']:.3f} USD; {paths[0]}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
