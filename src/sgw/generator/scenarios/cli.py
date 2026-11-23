"""`scenarios` command group: generate the second-tier scenario fixtures, check them, build the what-if grid.

Runs as `uv run python -m sgw.generator.scenarios <cmd>`; once `src/sgw/cli/commands/scenarios.py` re-exports
`app`, the same commands are `uv run sgw scenarios <cmd>`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Annotated, Any

import typer

from sgw.common.telemetry import sgw_span
from sgw.contracts.vocab import Classification, RunMode
from sgw.generator.scenarios import bluesky, heat, tablerock, weather

app = typer.Typer(
    name="scenarios", help="Scenario-lite: blue-sky + Readiness, Table Rock, heatwave, what-if."
)

BUILDERS = {"bluesky": bluesky.build, "tablerock": tablerock.build, "heat": heat.build}
NAMES = tuple(BUILDERS)


def generate_all(root: Path, names: tuple[str, ...] = NAMES) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        with sgw_span(
            "scenarios.generate",
            run_id=f"scenarios-{name}",
            classification=Classification.C1,
            user_role="system",
            run_mode=RunMode.REPLAY,
            node=name,
        ):
            d = root / name
            d.mkdir(parents=True, exist_ok=True)
            BUILDERS[name](d)
            manifest: dict[str, Any] = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            out[name] = str(manifest["combined_sha256"])
    return out


def _names(name: str) -> tuple[str, ...]:
    if name == "all":
        return NAMES
    if name not in BUILDERS:
        raise typer.BadParameter(f"unknown scenario {name!r}; one of {', '.join(NAMES)} or all")
    return (name,)


@app.command("generate")
def generate(
    name: Annotated[str, typer.Argument(help="bluesky, tablerock, heat or all")] = "all",
    out: Annotated[Path | None, typer.Option("--out", help="Root folder (default data/fixtures).")] = None,
) -> None:
    """Write the fixtures and print the combined hash per scenario."""
    for k, v in generate_all(out or weather.FIXTURES, _names(name)).items():
        typer.echo(f"{k}: {v}")


@app.command("check")
def check(name: Annotated[str, typer.Argument(help="bluesky, tablerock, heat or all")] = "all") -> None:
    """Regenerate into a temp folder twice; fail unless both runs and the committed manifests agree."""
    names = _names(name)
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        first, second = generate_all(Path(a), names), generate_all(Path(b), names)
    bad = []
    for n in names:
        committed = json.loads((weather.FIXTURES / n / "manifest.json").read_text(encoding="utf-8"))
        same = first[n] == second[n] == committed["combined_sha256"]
        typer.echo(f"{n}: {first[n]} {'ok' if same else 'MISMATCH'}")
        if not same:
            bad.append(n)
    if bad:
        raise typer.Exit(1)


@app.command("whatif")
def whatif() -> None:
    """Rebuild the precomputed Helene what-if grid (81 truth runs, about two minutes)."""
    from sgw.models.whatif import grid

    g = grid.build()
    typer.echo(f"{len(g['cells'])} cells, sha256 {g['cells_sha256']}")


@app.command("fit-ignition")
def fit_ignition() -> None:
    """Refit the ignition logit weights in-sample and leave-one-month-out; print the FFWI dependence."""
    from sgw.generator.scenarios import fireweather, tablerock
    from sgw.models.wildfire import ranking as rk

    veg = tablerock.veg_mean()
    _, year = fireweather.calibration(veg)
    observed = {int(m): float(v) for m, v in rk.value("validation", "observed_month_share_pct").items()}
    best = rk.fit_weights(year, veg, observed, KBDI_GRID, FFWI_GRID)[0]
    result: dict[str, Any] = {"in_sample": {"kbdi": best.kbdi_coef, "ffwi": best.ffwi_coef}, "loo": []}
    for held in observed:
        fit = rk.fit_weights(
            year, veg, {m: v for m, v in observed.items() if m != held}, KBDI_GRID, FFWI_GRID
        )[0]
        pred = round(fit.shares[held], 1)
        result["loo"].append(
            {
                "held_out": held,
                "kbdi": fit.kbdi_coef,
                "ffwi": fit.ffwi_coef,
                "predicted": pred,
                "observed": observed[held],
                "error": round(pred - observed[held], 1),
            }
        )
    fw = fireweather.gsp()
    window = rk.drivers(fw.between(*tablerock.WINDOW), fw.kbdi_by_day)
    result["ffwi_sensitivity"] = {
        f"{fc:g}": round(tablerock.ffwi_ratio(fc, window, year), 1) for fc in FFWI_SWEEP
    }
    typer.echo(json.dumps(result, indent=1))


KBDI_GRID = (0.0, 0.125, 0.25, 0.375, 0.5)
FFWI_GRID = (1.6, 2.0, 2.4, 2.8, 3.2, 3.6, 4.0)
FFWI_SWEEP = (0.8, 1.2, 1.6, 2.0, 2.4, 2.8)


@app.command("derive-weather")
def derive_weather(
    raw: Annotated[Path, typer.Option("--raw", help="R05 asos_hourly_5stn_2023-01_2025-03.csv")],
) -> None:
    """Re-derive the committed station extracts from the IEM download."""
    typer.echo(json.dumps(weather.derive(raw)))
