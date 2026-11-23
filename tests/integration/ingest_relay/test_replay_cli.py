from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sgw.cli.main import build_app
from sgw.ingest.testing import ScratchDb

pytestmark = pytest.mark.slow


def test_sgw_replay_twice_fresh_exports_identical_bytes(
    scratch_db: ScratchDb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SGW_DATABASE_URL", scratch_db.runtime_url)
    monkeypatch.setenv("SGW_OWNER_DATABASE_URL", scratch_db.admin_url)
    runner = CliRunner()
    app = build_app()
    outputs = []
    for name in ("a.jsonl", "b.jsonl"):
        result = runner.invoke(
            app, ["replay", "--scenario", "helene_micro", "--fresh", "--export", str(tmp_path / name)]
        )
        assert result.exit_code == 0, result.output
        assert "dq: error_failed=0" in result.output and "gapless=True" in result.output
        outputs.append((tmp_path / name).read_bytes())
    assert outputs[0] == outputs[1] and outputs[0].count(b"\n") > 180


def test_sgw_replay_refuses_fresh_on_main_database_and_naive_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SGW_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/sgw")
    runner = CliRunner()
    app = build_app()
    refused = runner.invoke(app, ["replay", "--scenario", "helene_micro", "--fresh"])
    assert refused.exit_code != 0 and "--yes" in refused.output
    bad_clock = runner.invoke(app, ["replay", "--scenario", "helene_micro", "--as-of", "2024-09-27T00:00:00"])
    assert bad_clock.exit_code != 0 and "zone" in bad_clock.output
