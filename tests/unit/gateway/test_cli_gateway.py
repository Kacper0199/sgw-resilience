from __future__ import annotations

import uvicorn
from typer.testing import CliRunner

from sgw.cli.main import build_app

from .gateway_testkit import FAKE_KEY

runner = CliRunner()


def test_llm_spend_summarises_ledger(tmp_path):
    csv = tmp_path / "spend.csv"
    csv.write_text(
        "ts,mode,purpose,wave,run_id,node,prompt_version,model,effort,batch,input_tokens,"
        "cache_creation_input_tokens,cache_read_input_tokens,output_tokens,stop_reason,latency_ms,cost_usd,"
        "request_hash,billed,attempts,status\n"
        "t,record,spike,W0,r,spike.narrate,,claude-sonnet-5-5,medium,False,10,0,0,5,end_turn,1,0.25,h,True,1,200\n"
    )
    result = runner.invoke(build_app(), ["llm-spend", "--csv", str(csv)])
    assert result.exit_code == 0, result.output
    assert "TOTAL | calls=1 | usd=0.25" in result.output


def test_gateway_record_without_key_exits_with_hint(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(build_app(), ["gateway", "--mode", "record"])
    assert result.exit_code == 2
    assert "--env-file" in result.output


def test_gateway_replay_starts_uvicorn(monkeypatch):
    calls = {}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.update(kw, app=app))
    result = runner.invoke(build_app(), ["gateway", "--port", "8107"])
    assert result.exit_code == 0, result.output
    assert calls["port"] == 8107 and calls["host"] == "127.0.0.1"
    assert FAKE_KEY not in result.output
