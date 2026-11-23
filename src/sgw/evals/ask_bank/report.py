"""Ask bank report: pass rates overall and by class, persona, language, moment, page, split and tag; grader
failure counts; latency and spend. JSON for machines, Markdown for people."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

DIMENSIONS = ("klass", "persona", "lang", "moment", "page", "split")


INFRA_TEXT = "The AI is not available right now"


def infra(row: Mapping[str, Any]) -> bool:
    """Not a verdict on Ask: the harness failed (HTTP error) or no model answered (spend cap, gateway). A role
    that may not start Ask at all (`role_blocked`) is a product failure, not infra."""
    if "role_blocked" in str(row.get("error")):
        return False
    no_model = row.get("reason") == "llm_unavailable" or INFRA_TEXT in str(row.get("text"))
    return bool(row.get("error")) or no_model


def rate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    passed = sum(bool(r["pass"]) for r in rows)
    return {"n": n, "passed": passed, "pass_rate": round(passed / n, 3) if n else 0.0}


def by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key))].append(r)
    return {k: rate(v) for k, v in sorted(groups.items())}


def by_tag(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        for t in r.get("tags") or []:
            groups[t].append(r)
    return {k: rate(v) for k, v in sorted(groups.items())}


def pct(values: Iterable[float], q: float) -> float:
    v = sorted(values)
    if not v:
        return 0.0
    return round(v[min(len(v) - 1, int(round(q * (len(v) - 1))))], 2)


def build(meta: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    latencies = [float(r["latency_s"]) for r in rows if not r.get("error")]
    failures = Counter(f for r in rows for f in r.get("failed") or [])
    paths = Counter(str(r.get("path")) for r in rows)
    reasons = Counter(str(r.get("reason")) for r in rows)
    usd = sum(float(r.get("usd") or 0) for r in rows)
    valid = [r for r in rows if not infra(r)]
    summary = {
        **rate(rows),
        "infra": len(rows) - len(valid),
        "valid": rate(valid),
        "usd": round(usd, 4),
        "usd_per_item": round(usd / len(rows), 5) if rows else 0.0,
        "live_calls": sum(int(r.get("live_calls") or 0) for r in rows),
        "latency_p50_s": round(statistics.median(latencies), 2) if latencies else 0.0,
        "latency_p95_s": pct(latencies, 0.95),
        "errors": sum(1 for r in rows if r.get("error")),
        "grader_failures": dict(failures.most_common()),
        "paths": dict(paths.most_common()),
        "reasons": dict(reasons.most_common()),
    }
    return {
        "meta": dict(meta),
        "summary": summary,
        "by": {d: by(rows, d) for d in DIMENSIONS},
        "by_tag": by_tag(rows),
        "items": list(rows),
    }


def _table(title: str, groups: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out = [f"### {title}", "", "| Group | Pass | n | Rate |", "| --- | ---: | ---: | ---: |"]
    out += [f"| {k} | {v['passed']} | {v['n']} | {v['pass_rate']:.2f} |" for k, v in groups.items()]
    return [*out, ""]


def _counts(c: Mapping[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in c.items())


def markdown(data: Mapping[str, Any]) -> str:
    m, s = data["meta"], data["summary"]
    lines = [
        f"# Ask bank report: {m['label']}",
        "",
        f"Commit `{m['commit']}`, split `{m['split']}`{' (smoke)' if m.get('smoke') else ''}, gateway"
        f" `{m['gateway_mode']}`, wave `{m['wave']}`, started {m['started_utc']}, {m['seconds']} s.",
        "",
        f"**Pass {s['passed']}/{s['n']} = {s['pass_rate']:.2f}**; without the {s['infra']} infra misses"
        f" (harness error, no model answer): {s['valid']['passed']}/{s['valid']['n']} ="
        f" {s['valid']['pass_rate']:.2f}. Spend {s['usd']:.3f} USD"
        f" ({s['live_calls']} live calls, {s['usd_per_item']:.4f} USD/item);"
        f" latency p50 {s['latency_p50_s']} s,"
        f" p95 {s['latency_p95_s']} s; errors {s['errors']}.",
        "",
        *(
            [
                f"LLM judge (uncalibrated, informative): pass {s['judge_pass_rate']} on"
                f" {data['judge']['scored']} sampled answers, mean helpful {data['judge']['mean_helpful']},"
                f" plain {data['judge']['mean_plain']}.",
                "",
            ]
            if data.get("judge")
            else []
        ),
        "Grader failures: "
        + (", ".join(f"{k} {v}" for k, v in s["grader_failures"].items()) or "none")
        + ".",
        "Answer paths: " + _counts(s["paths"]) + ".",
        "Reasons: " + _counts(s["reasons"]) + ".",
        "",
    ]
    titles = {"klass": "By class", "persona": "By persona", "lang": "By language", "moment": "By moment"}
    titles |= {"page": "By page", "split": "By split"}
    for dim, title in titles.items():
        lines += _table(title, data["by"][dim])
    lines += _table("By tag", data["by_tag"])
    lines += [
        "### Failed items",
        "",
        "| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |",
    ]
    lines += ["| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in data["items"]:
        if r["pass"]:
            continue
        if r.get("redacted"):
            lines.append(
                f"| {r['id']} | {r['klass']} | {r['lang']} | {r['persona']} | {r['moment']} |"
                f" {', '.join(r['failed'])} | held out | (redacted) |"
            )
            continue
        text = " ".join(str(r.get("text") or r.get("error") or "").split())[:110].replace("|", "/")
        lines.append(
            f"| {r['id']} | {r['klass']} | {r['lang']} | {r['persona']} | {r['moment']} |"
            f" {', '.join(r['failed'])} | {r.get('path')}/{r.get('reason')} | {text} |"
        )
    return "\n".join(lines) + "\n"


HELDOUT_KEEP = (
    "id",
    "split",
    "klass",
    "lang",
    "persona",
    "moment",
    "page",
    "tags",
    "pass",
    "failed",
    "checks",
)


def redact(row: Mapping[str, Any]) -> dict[str, Any]:
    """A held-out row as developers may see it: outcome only, no question, turns, expectations or answer."""
    if row.get("split") != "heldout":
        return dict(row)
    return {k: row[k] for k in HELDOUT_KEEP if k in row} | {"redacted": True}


def private_dir() -> Path:
    """Full held-out rows live outside git (var/ of the shared state root is git-ignored)."""
    from sgw.cli.support import var_dir

    return var_dir() / "evals" / "ask_bank_private"


def write(data: Mapping[str, Any], out: Path, label: str, private: Path | None = None) -> tuple[Path, Path]:
    """The report for the repo, with held-out rows redacted; when any row is held out, the full report goes
    to `private` (default `private_dir()`) for regrading."""
    out.mkdir(parents=True, exist_ok=True)
    rows = list(data["items"])
    if any(r.get("split") == "heldout" for r in rows):
        target = private or private_dir()
        target.mkdir(parents=True, exist_ok=True)
        full = json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n"
        (target / f"{label}.json").write_text(full, encoding="utf-8")
    public = {**data, "items": [redact(r) for r in rows]}
    if public.get("judge"):
        held = {r["id"] for r in rows if r.get("split") == "heldout"}
        items = {k: v for k, v in public["judge"]["items"].items() if k not in held}
        public["judge"] = {**public["judge"], "items": items}
    j, md = out / f"{label}.json", out / f"{label}.md"
    j.write_text(json.dumps(public, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    md.write_text(markdown(public), encoding="utf-8")
    return j, md
