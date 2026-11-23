"""The sgw/python image must carry every repository folder the api and worker read at request or job time.

The image copies a fixed list of folders (`docker/python/Dockerfile`) out of a context filtered by
`Dockerfile.dockerignore`; a folder missing from either is absent in the container while host tests pass.
G1 found the procedure corpus and the K17 reports missing, so water_continuity could not find its in-force
rule and the model evaluation route answered 404 on the live stack."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sgw.agent.rag import corpus
from sgw.models.outage import backtest
from sgw.ops import eval_reports, health
from sgw.reference import load

ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "docker" / "python"


def _copied() -> set[str]:
    text = (DOCKER / "Dockerfile").read_text(encoding="utf-8").replace("\\\n", " ")
    loop = re.search(r"for d in (.+?); do", text)
    assert loop, "the runtime stage copies repository folders in one `for d in ...; do` loop"
    return set(loop.group(1).split())


def _allowed() -> set[str]:
    lines = (DOCKER / "Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines()
    return {line[1:].rstrip("/") for line in lines if line.startswith("!")}


def _folder(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


RUNTIME_DIRS = {
    "procedure corpus (rag, water_continuity rules, copilot)": corpus.CORPUS_DIR,
    "K17 evaluation reports (/api/models/{name}/evaluation)": eval_reports.REPORTS_DIR,
    "health model cards": health.REPORTS_DIR,
    "outage backtest report": backtest.REPORT_PATH.parent,
    "map reference": load.COUNTIES_PATH.parent,
}


@pytest.mark.parametrize("what", sorted(RUNTIME_DIRS))
def test_runtime_folder_is_in_the_image(what: str) -> None:
    folder = _folder(RUNTIME_DIRS[what])
    assert folder in _copied(), f"{what}: add {folder} to the copy loop in docker/python/Dockerfile"
    assert folder in _allowed(), f"{what}: add !{folder}/ to docker/python/Dockerfile.dockerignore"
    assert (ROOT / folder).is_dir()


def test_private_paths_stay_out_of_the_image() -> None:
    for private in ("evals/heldout", "materials", "raw", "var", ".env"):
        assert private not in _copied() and private not in _allowed()


def test_the_embedding_model_is_read_from_the_image_not_written_under_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The container root is read-only: the copilot's query embedder must load the model the image baked
    into FASTEMBED_CACHE_PATH, never create `/app/var/models` (G1: `[Errno 30] Read-only file system`)."""
    from sgw.agent.rag import embed

    text = (DOCKER / "Dockerfile").read_text(encoding="utf-8")
    baked = re.search(r"FASTEMBED_CACHE_PATH=(\S+)", text)
    assert baked and "cache_dir='/opt/models'" in text and baked.group(1) == "/opt/models"
    monkeypatch.delenv("SGW_FASTEMBED_CACHE", raising=False)
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", baked.group(1))
    assert embed.model_cache_dir() == Path("/opt/models")
    monkeypatch.setenv("SGW_FASTEMBED_CACHE", "/srv/sgw-models")
    assert embed.model_cache_dir() == Path("/srv/sgw-models")


IMAGE_ONLY_PROBE = """
from datetime import UTC, datetime
from sgw.opendata import read
record = read.official_record(datetime(2024, 9, 30, tzinfo=UTC))
assert record.declarations, "no declarations"
assert read.county_names(), "no county names"
print("ok")
"""


def test_official_record_reads_only_files_the_image_carries(tmp_path: Path) -> None:
    """DR High 3: `/api/after-action/official-record` answered 500 on the live stack because the county
    names were read from `web/src/...`, which the image does not carry. Runs the read with a tree holding only
    `src/` and the copied folders."""
    import shutil
    import subprocess
    import sys

    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for folder in sorted(_copied() & _allowed()):
        if (ROOT / folder).is_dir():
            (tmp_path / folder).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / folder).symlink_to(ROOT / folder, target_is_directory=True)
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{tmp_path / 'src'}:{tmp_path}", "HOME": str(tmp_path)}
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", IMAGE_ONLY_PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == "ok"
