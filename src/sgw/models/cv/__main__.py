"""`uv run python -m sgw.models.cv build|verify`: review queue and K17 reference report from the scores."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from sgw.models.cv import queue as q


def _code_version() -> str:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            cwd=q.ROOT,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _dump(obj: object) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def build() -> int:
    """Queue, CSV and K17 report; also stamps the queue hash and its disclosure fields into manifest.json."""
    manifest = q.load_json(q.ARTEFACTS / "manifest.json")
    scores = q.load_json(q.ARTEFACTS / manifest["scores_file"])
    sample = q.load_json(q.ARTEFACTS / manifest["sample_file"])
    queue = q.build_queue(scores, sample, q.load_json(q.TRUTH_TABLE))
    (q.ARTEFACTS / "review_queue.json").write_text(_dump(queue), encoding="utf-8")
    (q.ARTEFACTS / "review_queue.csv").write_text(q.queue_csv(queue), encoding="utf-8")
    manifest["review_queue_file"] = "review_queue.json"
    manifest["review_queue_sha256"] = q.sha256_file(q.ARTEFACTS / "review_queue.json")
    manifest["acceptance_history"] = queue["acceptance_history"]
    manifest["honest_miss"] = queue["honest_miss"]
    (q.ARTEFACTS / "manifest.json").write_text(_dump(manifest), encoding="utf-8")
    report_path = q.ARTEFACTS / "ladi_reference_eval.json"
    created = manifest["created_at"]
    if report_path.exists():
        created = q.load_json(report_path).get("created_at", created)
    report = q.reference_eval_report(_code_version(), created)
    report_path.write_text(_dump(report), encoding="utf-8")
    order = queue["seeded_order"]
    print(f"queue: {len(queue['rows'])} photos; seeded cases by score: {', '.join(order['ranked_cases'])}")
    print(
        f"tier violations {order['tier_violations']}; moderate-or-worse min score "
        f"{order['structural_min_score']} vs control-group max {order['control_group_max_score']}; "
        f"ladder discordant pairs {order['ladder_discordant_pairs']}/{order['ladder_pairs']}; "
        f"honest miss: {queue['honest_miss']}"
    )
    return 0


def verify() -> int:
    problems = q.verify()
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if not problems:
        manifest = q.load_json(q.ARTEFACTS / "manifest.json")
        model = manifest["model"]
        print(f"OK manifest, scores, queue and thumbnails agree ({model['id']}@{model['revision'][:7]})")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sgw.models.cv", description=__doc__)
    parser.add_argument("command", choices=["build", "verify"])
    args = parser.parse_args(argv)
    if args.command == "build":
        return build()
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
