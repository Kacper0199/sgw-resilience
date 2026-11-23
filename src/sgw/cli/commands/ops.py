from __future__ import annotations

import typer

from sgw.ops.cli import app as _ops

app = typer.Typer(name="ops", help=_ops.info.help, no_args_is_help=True)
app.registered_commands.extend(_ops.registered_commands)
app.registered_groups.extend(_ops.registered_groups)

__all__ = ["app"]
