"""`sgw data generate|verify|calibrate`: the synthetic scenario generator (K9 fixtures)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(name="data", help="Synthetic scenario generator (family A).", no_args_is_help=True)

SCENARIO = Annotated[str, typer.Option(help="scenario file under data/synthetic/")]


@app.command("generate")
def generate(
    scenario: SCENARIO = "helene",
    out: Annotated[Path | None, typer.Option(help="output folder (default data/fixtures/<scenario>)")] = None,
) -> None:
    """Generate the scenario's K9 fixtures, network, ensembles and truth table."""
    from sgw.generator.scenario import generate as run

    result = run(scenario, out)
    seeded = result.truth_table["seeded_cases"]
    hinge = next((c["outcome"] for c in seeded if c["id"] == "HINGE-PS17-N-N1"), {})
    m = result.truth_table["metrics"]
    typer.echo(f"wrote {result.out_dir} ({result.event_count} events, {len(seeded)} seeded cases)")
    typer.echo(f"scenario_sha256 {result.manifest['scenario_sha256']}")
    typer.echo(f"t50 {m['county_t50_median_h']:.2f} h (target {m['county_t50_target_h']} h)")
    if hinge:
        typer.echo(
            f"PS-17 effective decide-by (quoted) N {hinge['effective_decide_by_N_utc']} -> "
            f"N+1 {hinge['effective_decide_by_N1_utc']} ({hinge['effective_shift_min']:+.0f} min); "
            f"own clock {hinge['decide_by_N_utc']} -> {hinge['decide_by_N1_utc']}"
        )


@app.command("verify")
def verify(scenario: SCENARIO = "helene", out: Annotated[Path | None, typer.Option()] = None) -> None:
    """Check every generated file against the manifest and re-read each K9 fixture."""
    from sgw.contracts.fixtures import read_fixture
    from sgw.generator.config import FIXTURES_DIR

    folder = out or FIXTURES_DIR / scenario
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    bad = []
    for name, info in sorted(manifest["files"].items()):
        digest = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        if digest != info["sha256"]:
            bad.append(name)
        if name.endswith(".jsonl"):
            header, _ = read_fixture(folder / name)
            if header.body_sha256 != info["body_sha256"]:
                bad.append(f"{name} (body)")
    if bad:
        typer.echo("manifest mismatch: " + ", ".join(bad), err=True)
        raise typer.Exit(1)
    typer.echo(f"ok {len(manifest['files'])} files, scenario_sha256 {manifest['scenario_sha256']}")


@app.command("calibrate")
def calibrate(scenario: SCENARIO = "helene") -> None:
    """Bisect `restoration.repair_scale` to the Helene county t50; prints the value to record in family A."""
    from sgw.generator.calibrate import calibrate_repair_scale

    c = calibrate_repair_scale(scenario)
    typer.echo(f"repair_scale {c.scale} gives t50 {c.t50_h:.3f} h")
    typer.echo(f"target {c.target_h} h, {c.iterations} bisection steps")
