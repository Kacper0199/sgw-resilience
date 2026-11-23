from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from sgw.cli.support import CliError, guard

app = typer.Typer()


@app.command("photos")
@guard
def photos(
    dest: Annotated[
        Path | None, typer.Option("--dest", help="Image folder (default: SGW_CV_IMAGES_DIR or var/cv).")
    ] = None,
) -> None:
    """Download the 200 LADI v2 damage photos (about 60 MB, CC BY 4.0) for the photo preview; sha256 checked.

    The images stay on this machine in a git-ignored folder; the API serves them to signed-in users and falls
    back to the committed thumbnails when they are missing."""
    from sgw.models.cv import images, read

    folder = dest or images.images_dir()
    script = read.ROOT / "host" / "cv" / "ladi_fetch.py"
    if not script.is_file():
        raise CliError(f"{script} is missing; run from a full checkout")
    done = subprocess.run([sys.executable, str(script), "fetch", "--dest", str(folder)], check=False)  # noqa: S603
    if done.returncode != 0:
        raise CliError("some photos failed the download or the sha256 check; run `uv run sgw photos` again")
    typer.echo(f"photos ready in {folder}")
