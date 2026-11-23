from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from sgw.cli.commands.commitments import app


def test_after_action_prints_the_evidence_and_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "evidence.json"
    result = CliRunner().invoke(app, ["after-action", "--scenario", "helene", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "fuel_truck_dispatch" in result.output and "propose" in result.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["method"]["label"].startswith("synthetic")
    assert {r["key"] for r in body["rows"]} == {"portable_generator_hookup", "fuel_truck_dispatch"}


def test_after_action_unknown_scenario_fails() -> None:
    result = CliRunner().invoke(app, ["after-action", "--scenario", "no-such-storm"])
    assert result.exit_code != 0
