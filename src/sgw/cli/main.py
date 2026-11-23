"""Entry point of the `sgw` command line (K20).

Every module in `sgw/cli/commands/` that exposes `app = typer.Typer()` is loaded at start-up.
A Typer created with a `name` is mounted as a command group under that name; otherwise its
commands are added at the top level, so `commands/stack.py` gives `sgw up`, `sgw down`, ...
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import typer

COMMANDS_DIR = Path(__file__).resolve().parent / "commands"
COMMANDS_PACKAGE = "sgw.cli.commands"


class CommandConflictError(RuntimeError):
    pass


def discover_modules(directory: Path = COMMANDS_DIR) -> list[str]:
    return sorted(
        info.name
        for info in pkgutil.iter_modules([str(directory)])
        if not info.name.startswith("_") and not info.ispkg
    )


def _command_name(command: typer.models.CommandInfo) -> str:
    if command.name:
        return command.name
    callback = command.callback
    assert callback is not None
    return callback.__name__.replace("_", "-")


def _group_name(group: typer.models.TyperInfo) -> str:
    instance_name = group.typer_instance.info.name if group.typer_instance else None
    for candidate in (group.name, instance_name):
        if isinstance(candidate, str) and candidate:
            return candidate
    raise CommandConflictError("a mounted command group has no name")


def mount(root: typer.Typer, module_name: str, sub: typer.Typer, taken: dict[str, str]) -> None:
    group_name = sub.info.name if isinstance(sub.info.name, str) else None
    if group_name:
        if group_name in taken:
            raise CommandConflictError(
                f"'{group_name}' from {module_name} already defined by {taken[group_name]}"
            )
        taken[group_name] = module_name
        root.add_typer(sub, name=group_name)
        return
    names = [_command_name(c) for c in sub.registered_commands]
    names += [_group_name(g) for g in sub.registered_groups]
    seen: set[str] = set()
    for name in names:
        if name in taken or name in seen:
            owner = taken.get(name, module_name)
            raise CommandConflictError(f"'{name}' from {module_name} already defined by {owner}")
        seen.add(name)
    for name in names:
        taken[name] = module_name
    root.registered_commands.extend(sub.registered_commands)
    root.registered_groups.extend(sub.registered_groups)


def build_app(package: str = COMMANDS_PACKAGE, directory: Path = COMMANDS_DIR) -> typer.Typer:
    root = typer.Typer(
        name="sgw",
        help="SGW Resilience Decision Platform: run, check and operate the local stack.",
        no_args_is_help=True,
        add_completion=False,
        pretty_exceptions_show_locals=False,
    )
    taken: dict[str, str] = {}
    for module_name in discover_modules(directory):
        module = importlib.import_module(f"{package}.{module_name}")
        sub = getattr(module, "app", None)
        if isinstance(sub, typer.Typer):
            mount(root, module_name, sub, taken)
    return root


app = build_app()

if __name__ == "__main__":
    app()
