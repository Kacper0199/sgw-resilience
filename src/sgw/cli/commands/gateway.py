"""`sgw gateway` and `sgw llm-spend`: the LLM gateway and its spend ledger summary."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from sgw.cli.support import llm_env_file, llm_spend_dir, repo_root

app = typer.Typer()

MODES = ("replay", "record", "live")


def _import_gateway() -> None:
    root = str(repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)


@app.command("gateway")
def gateway(
    mode: Annotated[str, typer.Option(help="replay (no key), record or live")] = "replay",
    host: Annotated[str, typer.Option(help="bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="listen port")] = 8100,
) -> None:
    """Run the LLM gateway, the only egress to the Anthropic API."""
    if mode not in MODES:
        typer.echo(f"--mode must be one of {', '.join(MODES)}", err=True)
        raise typer.Exit(2)
    if mode != "replay" and not os.environ.get("ANTHROPIC_API_KEY"):
        typer.echo(
            f"--mode {mode} needs the key in the environment; run: "
            f"uv run --env-file {llm_env_file()} sgw gateway --mode {mode}",
            err=True,
        )
        raise typer.Exit(2)
    os.environ["LLM_MODE"] = mode
    _import_gateway()
    import logging

    import uvicorn
    from services.llm_gateway.api import create_app

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


@app.command("llm-spend")
def llm_spend(
    by: Annotated[str, typer.Option(help="comma-separated columns to group by")] = "wave,purpose,node",
    csv: Annotated[Path | None, typer.Option(help="ledger path (default var/llm/llm_spend.csv)")] = None,
) -> None:
    """Summarise the gateway spend ledger (calls, USD, tokens)."""
    _import_gateway()
    from services.llm_gateway.spend import SpendLedger, format_summary

    ledger = SpendLedger(csv or Path(os.environ.get("LLM_SPEND_CSV", llm_spend_dir() / "llm_spend.csv")))
    keys = tuple(k.strip() for k in by.split(",") if k.strip())
    for line in format_summary(ledger, keys):
        typer.echo(line)
