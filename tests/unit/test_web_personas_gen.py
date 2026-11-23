"""The web app reads the demo identities from a file generated out of data/seed/users.yaml."""

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_generated_personas_match_the_seed_file() -> None:
    script = runpy.run_path(str(ROOT / "web/scripts/build_personas.py"))
    assert script["is_current"](), "run `uv run --frozen python web/scripts/build_personas.py`"
