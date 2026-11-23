"""Repository guards for check.sh, lefthook and CI. Standard library only, runs on macOS, Linux and Windows.

Usage: python scripts/guards.py <command>
  commands: forbidden-paths [--staged], markers, test-counts, pinned-actions
Exit 0 pass, 1 guard failed, 2 could not evaluate.
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 20 * 1024 * 1024
FORBIDDEN_PATH = re.compile(
    r"^(raw|out)/"
    r"|(^|/)\.env[^/]*$"
)
ALLOWED_ENV_FILE = re.compile(r"(^|/)\.env\.example$")
ALLOW_SKIP_TOKEN = re.compile(r"sgw-allow-skip:\s*\S+")
PY_MARKER = re.compile(
    r"\bmark\.(skip|skipif|xfail)\b|pytest\.(skip|xfail|importorskip)\s*\("
    r"|add_marker\(\s*[\"']?(skip|xfail)|unittest\.(skip\w*|expectedFailure)\b"
)
JS_MARKER = re.compile(
    r"(?<![\w.])(it|test|describe|suite|bench)\.(only|skip|todo|fails|fail|fixme|skipIf|runIf)\b"
    r"|(?<![\w.])(xit|xtest|xdescribe|fit|fdescribe)\s*\("
)
JS_TEST_CALL = re.compile(r"(?<![\w.])(it|test)(\.\w+)?\s*\(\s*['\"`]")
JS_TEST_FILE = re.compile(r"(^web/.*\.(test|spec)\.[cm]?[jt]sx?$)|(^tests/e2e/.*\.[cm]?[jt]sx?$)")
PY_SOURCE_DIRS = ("src", "tests", "scripts", "services")
USES_LINE = re.compile(r"^\s*-?\s*uses:\s*(\S+)")
PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


class GuardError(RuntimeError):
    pass


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)  # noqa: S603, S607
    if check and result.returncode != 0:
        raise GuardError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def git_bytes(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)  # noqa: S603, S607
    if result.returncode != 0:
        raise GuardError(f"git {' '.join(args)} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def repo_root() -> Path:
    return Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())


@dataclass(frozen=True)
class IndexEntry:
    path: str
    size: int


def index_entries(root: Path, staged_only: bool = False) -> list[IndexEntry]:
    raw = git(root, "ls-files", "-z", "--format=%(objectsize) %(path)")
    entries = []
    for record in raw.split("\0"):
        if not record:
            continue
        size, _, path = record.partition(" ")
        entries.append(IndexEntry(path=path, size=int(size) if size.isdigit() else 0))
    if staged_only:
        staged = set(
            git(root, "diff", "--cached", "--no-renames", "--name-only", "-z", "--diff-filter=d").split("\0")
        )
        entries = [entry for entry in entries if entry.path in staged]
    return entries


def forbidden_reasons(entries: Iterable[IndexEntry], max_bytes: int = MAX_FILE_BYTES) -> list[str]:
    problems = []
    for entry in entries:
        if FORBIDDEN_PATH.search(entry.path) and not ALLOWED_ENV_FILE.search(entry.path):
            fix = f"git rm --cached -- '{entry.path}'"
            problems.append(f"{entry.path}: private or local-only path. Fix: {fix}")
        elif entry.size > max_bytes:
            mib = entry.size / 1024 / 1024
            problems.append(
                f"{entry.path}: {mib:.1f} MiB is over the 20 MiB limit. "
                f"Fix: git rm --cached -- '{entry.path}' and publish it as a fetched data asset"
            )
    return problems


def resolve_base(root: Path) -> str:
    wanted = os.environ.get("CHECK_BASE", "main")
    for candidate in (wanted, f"origin/{wanted}"):
        if git(root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}", check=False).strip():
            return git(root, "merge-base", "HEAD", candidate).strip()
    fix = f"git fetch origin {wanted}, or set CHECK_BASE=<ref>"
    raise GuardError(f"base ref '{wanted}' not found. Fix: {fix}")


def added_lines(root: Path, base: str) -> list[tuple[str, str]]:
    diff = git(root, "diff", "--unified=0", "--no-renames", "--no-color", "--no-ext-diff", base)
    current = ""
    lines = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
        elif line.startswith("+") and current:
            lines.append((current, line[1:]))
    return lines


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if path.endswith(".py"):
        in_tests = path.startswith(("tests/", "scripts/tests/"))
        return in_tests or name.startswith("test_") or name == "conftest.py"
    return bool(JS_TEST_FILE.search(path))


def new_markers(lines: Iterable[tuple[str, str]]) -> tuple[list[str], list[str]]:
    blocked, allowed = [], []
    for path, text in lines:
        if not is_test_file(path):
            continue
        pattern = PY_MARKER if path.endswith(".py") else JS_MARKER
        if not pattern.search(text):
            continue
        where = f"{path}: {text.strip()[:120]}"
        (allowed if ALLOW_SKIP_TOKEN.search(text) else blocked).append(where)
    return blocked, allowed


def python_area(nodeid: str) -> str:
    parts = nodeid.split("::", 1)[0].replace("\\", "/").split("/")
    if parts[0] == "tests" and len(parts) > 2 and parts[1] == "unit":
        return f"py:tests/unit/{parts[2]}"
    if parts[0] == "tests" and len(parts) > 2:
        return f"py:tests/{parts[1]}"
    if parts[0] == "scripts" and len(parts) > 2:
        return "py:scripts/tests"
    return f"py:{parts[0]}"


def web_area(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "tests":
        return "web:tests/e2e"
    if len(parts) > 4 and parts[1] == "src" and parts[2] == "features":
        return f"web:features/{parts[3]}"
    return "web:" + "/".join(parts[1:3]) if len(parts) > 3 else "web:web"


def count_js_tests(files: dict[str, str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path, text in files.items():
        hits = len(JS_TEST_CALL.findall(text))
        if hits:
            counts[web_area(path)] += hits
    return counts


def collect_python(tree: Path) -> tuple[Counter[str], str]:
    tree = tree.resolve()
    targets = [name for name in ("tests", "scripts/tests") if (tree / name).is_dir()]
    if not targets:
        return Counter(), ""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(tree / d) for d in ("src", "services"))}
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--continue-on-collection-errors",
            "--rootdir",
            str(tree),
            *targets,
        ],
        cwd=tree,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    counts: Counter[str] = Counter(python_area(line) for line in result.stdout.splitlines() if "::" in line)
    problem = "" if result.returncode in (0, 5) else (result.stdout + result.stderr)[-1500:]
    return counts, problem


def js_files_at(root: Path, ref: str | None) -> dict[str, str]:
    if ref is None:
        paths = git(root, "ls-files", "-z").split("\0")
        found = [p for p in paths if JS_TEST_FILE.search(p) and (root / p).exists()]
        return {p: (root / p).read_text(errors="replace") for p in found}
    paths = git(root, "ls-tree", "-r", "-z", "--name-only", ref).split("\0")
    return {p: git(root, "show", f"{ref}:{p}") for p in paths if JS_TEST_FILE.search(p)}


def export_tree(root: Path, ref: str, dest: Path) -> None:
    present = set(git(root, "ls-tree", "--name-only", ref).split())
    wanted = [p for p in (*PY_SOURCE_DIRS, "pyproject.toml") if p in present]
    if not wanted:
        return
    payload = git_bytes(root, "archive", "--format=tar", ref, "--", *wanted)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        archive.extractall(dest, filter="data")


def compare_counts(
    base: Counter[str], head: Counter[str], allowed_drops: set[str]
) -> tuple[list[str], list[str]]:
    report, failures = [], []
    for area in sorted(set(base) | set(head)):
        before, after = base.get(area, 0), head.get(area, 0)
        delta = after - before
        flag = ""
        if delta < 0:
            flag = "  ALLOWED DROP" if area in allowed_drops else "  FEWER TESTS"
            if area not in allowed_drops:
                failures.append(
                    f"{area}: {before} -> {after} tests ({delta}). Fix: restore the removed tests, or, "
                    f"when tests moved on purpose, rerun with SGW_ALLOW_TEST_DROP={area} "
                    "and say why in the commit message"
                )
        report.append(f"  {area:<34} {before:>5} -> {after:<5}{flag}")
    return report, failures


def unpinned_actions(workflows: dict[str, str]) -> list[str]:
    problems = []
    for path, text in workflows.items():
        for number, line in enumerate(text.splitlines(), start=1):
            found = USES_LINE.match(line)
            if found and not found.group(1).startswith("./") and not PINNED_ACTION.match(found.group(1)):
                problems.append(
                    f"{path}:{number}: '{found.group(1)}' is not pinned to a full commit SHA. "
                    "Fix: gh api repos/<owner>/<repo>/commits/<tag> --jq .sha, "
                    "then uses: <action>@<sha> # <tag>"
                )
    return problems


def cmd_pinned_actions(root: Path) -> int:
    folder = root / ".github" / "workflows"
    files = sorted([*folder.glob("*.yml"), *folder.glob("*.yaml")]) if folder.is_dir() else []
    problems = unpinned_actions({f.relative_to(root).as_posix(): f.read_text() for f in files})
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


def cmd_forbidden(root: Path, staged: bool) -> int:
    problems = forbidden_reasons(index_entries(root, staged_only=staged))
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


def cmd_markers(root: Path) -> int:
    blocked, allowed = new_markers(added_lines(root, resolve_base(root)))
    for item in allowed:
        print(f"  allowed by sgw-allow-skip: {item}")
    for item in blocked:
        print(f"  new skip/xfail/only marker: {item}")
    if blocked:
        print("  Fix: remove the marker, or append 'sgw-allow-skip: <reason>'")
    return 1 if blocked else 0


def cmd_test_counts(root: Path) -> int:
    base = resolve_base(root)
    allowed = {a.strip() for a in os.environ.get("SGW_ALLOW_TEST_DROP", "").split(",") if a.strip()}
    head_py, head_problem = collect_python(root)
    with tempfile.TemporaryDirectory(prefix="sgw-base-") as tmp:
        base_tree = Path(tmp).resolve()
        export_tree(root, base, base_tree)
        base_py, _ = collect_python(base_tree)
    base_counts = base_py + count_js_tests(js_files_at(root, base))
    head_counts = head_py + count_js_tests(js_files_at(root, None))
    report, failures = compare_counts(base_counts, head_counts, allowed)
    print(f"  tests per area, base {base[:10]} -> working tree")
    print("\n".join(report) if report else "  (no tests on either side)")
    if head_problem:
        print(f"  pytest collection failed on the working tree:\n{head_problem}")
        failures.append("collection error")
    for failure in failures:
        print(f"  {failure}")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    forbidden = sub.add_parser("forbidden-paths")
    forbidden.add_argument("--staged", action="store_true")
    sub.add_parser("markers")
    sub.add_parser("test-counts")
    sub.add_parser("pinned-actions")
    args = parser.parse_args(argv)
    try:
        root = repo_root()
        if args.command == "forbidden-paths":
            return cmd_forbidden(root, args.staged)
        if args.command == "markers":
            return cmd_markers(root)
        if args.command == "test-counts":
            return cmd_test_counts(root)
        return cmd_pinned_actions(root)
    except GuardError as error:
        print(f"  {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
