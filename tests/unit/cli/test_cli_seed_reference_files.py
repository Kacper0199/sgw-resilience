"""`sgw seed --demo` names a missing map reference file and how to restore it, before touching
the database."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from sgw.cli.commands.seed import app
from sgw.reference import load


@pytest.mark.parametrize("attr", ["COUNTIES_PATH", "WORLD_PATH"])
def test_missing_reference_file_is_a_clear_cli_error(
    attr: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "gone" / Path(getattr(load, attr)).name
    monkeypatch.setattr(load, attr, missing)
    monkeypatch.setenv("DEMO_PASSWORD", "unused-in-this-test")
    monkeypatch.setattr("sgw.cli.commands.seed.load_demo_env", dict)
    result = CliRunner().invoke(app, ["seed", "--demo", "--database", "sgw_never_touched"])
    assert result.exit_code != 0
    out = result.output
    assert str(missing) in out and "git checkout" in out
    assert "demo seed failed" not in out
