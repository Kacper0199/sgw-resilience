from __future__ import annotations

import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sgw.cli.main import CommandConflictError, app, build_app

USER_COMMANDS = {"bootstrap", "up", "down", "reset", "stats", "db-smoke", "migrate", "doctor"}


def registered_names(typer_app) -> set[str]:
    import typer.main

    return set(typer.main.get_command(typer_app).commands)  # type: ignore[attr-defined]


def test_help_lists_every_wp03_user_command() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert registered_names(app) >= USER_COMMANDS


def test_no_init_files_in_namespace_packages() -> None:
    cli_dir = Path(__file__).resolve().parents[3] / "src" / "sgw"
    assert not (cli_dir / "__init__.py").exists()
    assert not (cli_dir / "cli" / "__init__.py").exists()
    assert not (cli_dir / "cli" / "commands" / "__init__.py").exists()


def make_package(tmp_path: Path, modules: dict[str, str]) -> tuple[str, Path]:
    name = f"sgwtest_{uuid.uuid4().hex[:8]}"
    directory = tmp_path / name
    directory.mkdir()
    for module, body in modules.items():
        (directory / f"{module}.py").write_text(textwrap.dedent(body))
    sys.path.insert(0, str(tmp_path))
    return name, directory


@pytest.fixture
def clean_path():
    before = list(sys.path)
    yield
    sys.path[:] = before


def test_flat_and_grouped_modules_are_mounted(tmp_path: Path, clean_path: None) -> None:
    package, directory = make_package(
        tmp_path,
        {
            "alpha": """
                import typer
                app = typer.Typer()

                @app.command()
                def hello() -> None:
                    print("hi")

                @app.command("contracts-check")
                def contracts_check() -> None:
                    print("checked")
            """,
            "beta": """
                import typer
                app = typer.Typer(name="data")

                @app.command()
                def fetch() -> None:
                    print("fetched")
            """,
            "_private": "raise RuntimeError('must not be imported')\n",
            "gamma": "VALUE = 1\n",
        },
    )
    built = build_app(package, directory)
    assert {"hello", "contracts-check", "data"} <= registered_names(built)
    runner = CliRunner()
    assert runner.invoke(built, ["contracts-check"]).output.strip() == "checked"
    assert runner.invoke(built, ["data", "fetch"]).output.strip() == "fetched"


def test_duplicate_command_names_fail_loudly(tmp_path: Path, clean_path: None) -> None:
    body = """
        import typer
        app = typer.Typer()

        @app.command()
        def up() -> None:
            pass
    """
    package, directory = make_package(tmp_path, {"one": body, "two": body})
    with pytest.raises(CommandConflictError, match="'up'"):
        build_app(package, directory)


def test_flat_module_group_clashing_with_a_command_fails(tmp_path: Path, clean_path: None) -> None:
    package, directory = make_package(
        tmp_path,
        {
            "one": """
                import typer
                app = typer.Typer()

                @app.command()
                def data() -> None:
                    pass
            """,
            "two": """
                import typer
                app = typer.Typer()
                inner = typer.Typer()
                app.add_typer(inner, name="data")

                @inner.command()
                def fetch() -> None:
                    pass
            """,
        },
    )
    with pytest.raises(CommandConflictError, match="'data' from two already defined by one"):
        build_app(package, directory)


def test_duplicate_names_inside_one_module_fail(tmp_path: Path, clean_path: None) -> None:
    package, directory = make_package(
        tmp_path,
        {
            "solo": """
                import typer
                app = typer.Typer()

                @app.command("same")
                def first() -> None:
                    pass

                @app.command("same")
                def second() -> None:
                    pass
            """,
        },
    )
    with pytest.raises(CommandConflictError, match="'same'"):
        build_app(package, directory)


def test_state_root_resolves_the_main_checkout_without_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sgw.cli import support

    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt" / "commondir").write_text("../..\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n")
    monkeypatch.delenv("SGW_STATE_ROOT", raising=False)
    monkeypatch.setattr(support.shutil, "which", lambda name: None)
    monkeypatch.setattr(support, "repo_root", lambda: worktree)
    assert support.state_root() == main.resolve()
    monkeypatch.setattr(support, "repo_root", lambda: main)
    assert support.state_root() == main.resolve()
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(support, "repo_root", lambda: plain)
    assert support.state_root() == plain
