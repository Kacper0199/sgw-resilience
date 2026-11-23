from __future__ import annotations

import json
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from typer.testing import CliRunner

from sgw.cli.commands.clocks import app
from sgw.common import telemetry
from sgw.models.clocks.job import run_clock_job
from sgw.models.clocks.ps17 import CASE_POWER, ps17_specs

DATA = Path(__file__).with_name("data") / "wp06_helene_ps17_members.json"
INPUTS = json.loads(DATA.read_text(encoding="utf-8"))


def test_job_span_carries_k12_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry.trace, "get_tracer", lambda name: provider.get_tracer(name))
    result = run_clock_job(ps17_specs(INPUTS["advisories"]["N"], INPUTS), run_id="run-clocks-n")
    assert CASE_POWER in result.cases
    (span,) = exporter.get_finished_spans()
    assert span.name == "clocks.compute"
    assert telemetry.missing_required(span.attributes) == []
    assert span.attributes is not None and span.attributes["sgw.region_id"] == "SC-45003"


def test_cli_compute_and_waterfall() -> None:
    runner = CliRunner()
    out = runner.invoke(app, ["compute", "--input", str(DATA), "--advisory", "N+1"])
    assert out.exit_code == 0, out.output
    assert "DC-D3-PS17-POWER" in out.output and "act_now" in out.output
    js = runner.invoke(app, ["compute", "--input", str(DATA), "--advisory", "N", "--json"])
    cases = {c["decision_case_id"]: c for c in json.loads(js.output)}
    assert cases[CASE_POWER]["no_regret_verdict"] == "wait_for_next_advisory"
    wf = runner.invoke(app, ["waterfall", "--input", str(DATA), "--case", CASE_POWER])
    assert wf.exit_code == 0, wf.output
    assert "lead_time.portable_generator_hookup" in wf.output and "bound by DC-D3-PS17-PRESSURE" in wf.output
    et = runner.invoke(app, ["event-type", "--p50", "1900000", "--p90", "2600000"])
    assert et.exit_code == 0 and "Type 1" in et.output and "Helene" in et.output
    bad = runner.invoke(app, ["compute", "--input", str(DATA), "--advisory", "N+9"])
    assert bad.exit_code != 0
