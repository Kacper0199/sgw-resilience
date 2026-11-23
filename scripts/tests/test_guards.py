from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from conftest import load_script, run_git

guards = load_script("guards")
SKIP_MARK = "@pytest.mark." + "skip"
ONLY_CALL = "it." + "only("


def entry(path: str, size: int = 10) -> object:
    return guards.IndexEntry(path=path, size=size)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".envrc",
        "web/.env.production",
        "services/llm_gateway/.env",
        "raw/x.txt",
        "out/demo-smoke.json",
    ],
)
def test_forbidden_paths_are_reported_with_a_fix(path: str) -> None:
    problems = guards.forbidden_reasons([entry(path)])
    assert len(problems) == 1
    assert "git rm --cached" in problems[0]


@pytest.mark.parametrize("path", [".env.example", "docs/env.md", "src/sgw/raw_feed.py", "web/src/out.ts"])
def test_allowed_paths_pass(path: str) -> None:
    assert guards.forbidden_reasons([entry(path)]) == []


def test_files_over_20_mib_are_reported() -> None:
    big = entry("data/open/tiles.pmtiles", guards.MAX_FILE_BYTES + 1)
    small = entry("data/open/ok.csv", guards.MAX_FILE_BYTES)
    problems = guards.forbidden_reasons([big, small])
    assert len(problems) == 1 and "20 MiB" in problems[0]


def test_index_entries_reads_sizes_and_staged_subset(repo: Path) -> None:
    (repo / "a.txt").write_text("12345")
    run_git(repo, "add", "a.txt")
    entries = {e.path: e.size for e in guards.index_entries(repo)}
    assert entries == {"README.md": 5, "a.txt": 5}
    assert [e.path for e in guards.index_entries(repo, staged_only=True)] == ["a.txt"]


def test_forbidden_staged_env_file_fails(repo: Path) -> None:
    (repo / ".env").write_text("NAME=value\n")
    run_git(repo, "add", "-f", ".env")
    assert guards.forbidden_reasons(guards.index_entries(repo, staged_only=True))


def test_new_markers_flag_python_and_web_tests() -> None:
    lines = [
        ("tests/unit/api/test_x.py", f"{SKIP_MARK}(reason='later')"),
        ("web/src/features/queue/Queue.test.tsx", f"{ONLY_CALL}'renders', () => {{}})"),
        ("src/sgw/api/app.py", f"{SKIP_MARK}"),
        ("tests/unit/api/test_y.py", f"{SKIP_MARK}  # sgw-allow-skip: needs OPA image"),
        ("tests/unit/api/test_z.py", "from pytest import mark; @mark." + "xfail"),
        ("tests/conftest.py", "item.add_" + "marker('skip')"),
    ]
    blocked, allowed = guards.new_markers(lines)
    assert len(blocked) == 4
    assert len(allowed) == 1 and "needs OPA image" in allowed[0]


def test_markers_against_base_use_merge_base(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_git(repo, "checkout", "-q", "-b", "w1/wp-07-feeds")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text(f"import pytest\n\n{SKIP_MARK}\ndef test_a():\n    pass\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "add skip")
    monkeypatch.chdir(repo)
    lines = guards.added_lines(repo, guards.resolve_base(repo))
    blocked, _ = guards.new_markers(lines)
    assert blocked == [f"tests/test_a.py: {SKIP_MARK}"]


def test_python_area_mapping() -> None:
    assert guards.python_area("tests/unit/api/test_x.py::test_a") == "py:tests/unit/api"
    assert guards.python_area("tests/contracts/test_k1.py::test_a[1]") == "py:tests/contracts"
    assert guards.python_area("scripts/tests/test_guards.py::test_a") == "py:scripts/tests"
    assert guards.python_area("tests/test_top.py::test_a") == "py:tests"


def test_js_test_counting_per_area() -> None:
    files = {
        "web/src/features/queue/Queue.test.tsx": (
            "it('a', () => {})\ntest(\"b\", () => {})\nit.each([1])('c')\n"
        ),
        "tests/e2e/journey.spec.ts": "test('login', async () => {})\n",
    }
    counts = guards.count_js_tests(files)
    assert counts == Counter({"web:features/queue": 2, "web:tests/e2e": 1})


def test_compare_counts_fails_on_drop_unless_allowed() -> None:
    base = Counter({"py:tests/unit/api": 10, "py:tests/contracts": 4})
    head = Counter({"py:tests/unit/api": 9, "py:tests/contracts": 6, "py:tests/unit/new": 1})
    _, failures = guards.compare_counts(base, head, set())
    assert len(failures) == 1 and "py:tests/unit/api: 10 -> 9" in failures[0]
    _, failures = guards.compare_counts(base, head, {"py:tests/unit/api"})
    assert failures == []


def test_test_counts_end_to_end_detects_removed_test(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "tests" / "unit" / "api").mkdir(parents=True)
    module = repo / "tests" / "unit" / "api" / "test_api.py"
    module.write_text("def test_one():\n    pass\n\n\ndef test_two():\n    pass\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "tests")
    run_git(repo, "checkout", "-q", "-b", "w1/wp-08-api")
    module.write_text("def test_one():\n    pass\n")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("SGW_ALLOW_TEST_DROP", raising=False)
    assert guards.cmd_test_counts(repo) == 1
    monkeypatch.setenv("SGW_ALLOW_TEST_DROP", "py:tests/unit/api")
    assert guards.cmd_test_counts(repo) == 0


def test_missing_base_names_the_fix(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHECK_BASE", "no-such-branch")
    with pytest.raises(guards.GuardError, match="git fetch origin no-such-branch"):
        guards.resolve_base(repo)


def test_unpinned_actions_are_reported() -> None:
    sha = "3d3c42e5aac5ba805825da76410c181273ba90b1"
    workflow = (
        f"steps:\n  - uses: actions/checkout@{sha} # v7.0.1\n  - uses: actions/setup-node@v7\n"
        "  - uses: ./.github/actions/local\n    uses: docker://alpine:3\n"
    )
    problems = guards.unpinned_actions({"ci.yml": workflow})
    assert [p.split(":")[1] for p in problems] == ["3", "5"]
