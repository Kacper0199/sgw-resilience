from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from sgw.cli.support import CliError, guard

app = typer.Typer(
    name="water",
    help="Water continuity twin (A4), WNTR check, PS-17 clock inputs, anomaly (A7), spoof guard (A8).",
)


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")


@app.command("validate")
@guard
def validate(
    out: Annotated[Path | None, typer.Option("--out", help="Report path.")] = None,
) -> None:
    """Reduced twin vs the WNTR precompute grid; fails when the median error exceeds 60 min."""
    from sgw.models.water.params import ARTEFACT_DIR
    from sgw.models.water.validate import compare

    grid = ARTEFACT_DIR / "wntr_drain_grid.json"
    if not grid.is_file():
        raise CliError(f"no WNTR grid at {grid}; run `make water-precompute` on the host first")
    report = compare()
    _write(out or ARTEFACT_DIR / "validation.json", report)
    for floor, block in report["floors"].items():
        for name, s in block["variants"].items():
            typer.echo(
                f"{floor:7} {name:22} n={s['n']} median |err| {s['median_abs_min']:.3f} min, "
                f"p90 {s['p90_abs_min']:.2f}, max {s['max_abs_min']:.2f}, bias {s['mean_signed_min']:+.2f}"
            )
    if not report["passed"]:
        raise CliError("reduced twin median error above 60 min")


@app.command("ps17-members")
@guard
def ps17_members(
    out: Annotated[Path | None, typer.Option("--out", help="Member table path.")] = None,
) -> None:
    """PS-17 per-member clock table (WP-12 input contract) with twin drain terms; prints old vs new drain."""
    import numpy as np

    from sgw.models.water.ps17_members import OUT_PATH, write_member_table

    table = write_member_table(out or OUT_PATH)
    meta = table["water_twin"]
    typer.echo(
        f"floor {meta['floor_citation']}; critical nodes {meta['critical_node_counts_members']} "
        f"(WNTR grid {meta['critical_node_counts_wntr']}); basis "
        f"{meta['drain_basis']['basis_id']}@{meta['drain_basis']['basis_version']}"
    )
    for label, adv in table["advisories"].items():
        new = [m["drain_to_floor_min"] for m in adv["members"] if m["drain_to_floor_min"] is not None]
        old = [
            m["drain_reference_wp06_min"] for m in adv["members"] if m["drain_reference_wp06_min"] is not None
        ]
        q_new = np.percentile(new, [10, 50, 90]).round(0)
        q_old = np.percentile(old, [10, 50, 90]).round(0)
        typer.echo(
            f"{label:4} drain P10/P50/P90 twin {q_new.tolist()} min, WP-06 reference {q_old.tolist()} min"
        )
    typer.echo(f"wrote {out or OUT_PATH}")


@app.command("survival")
@guard
def survival(
    samples: Annotated[int | None, typer.Option("--samples", help="Monte Carlo samples per station.")] = None,
    out: Annotated[Path | None, typer.Option("--out", help="Report path.")] = None,
) -> None:
    """Station continuity Monte Carlo on the helene scenario, with the PS-17 hookup curve."""
    from sgw.models.water.continuity import OUT_PATH, continuity_report

    report = continuity_report(samples=samples)
    _write(out or OUT_PATH, report)
    for s in report["stations"]:
        q = s["breach_after_loss_min_p10_p50_p90"]
        typer.echo(
            f"{s['station']:6} {s['generator']:8} P(breach {s['floor_psi']:g} psi, {s['horizon_h']:g} h) "
            f"{s['p_breach']:.3f} +- {s['p_breach_se']:.3f}; breach after loss P10/50/90 {q}; "
            f"causes {s['cause_share']}"
        )
    for c in report["ps17_hookup_curve"]:
        typer.echo(f"PS-17 hookup +{c['hookup_after_loss_min']:3d} min: P(breach) {c['p_breach']:.3f}")


@app.command("anomaly")
@guard
def anomaly(
    out: Annotated[Path | None, typer.Option("--out", help="Report path.")] = None,
    bench_days: Annotated[int, typer.Option("--bench-days", help="Dev-bench station-days.")] = 400,
) -> None:
    """A7/A8 on the helene dev fixture and the seeded dev bench (dev split only): recall and false alarms."""
    from sgw.models.anomaly.report import OUT_PATH, anomaly_report

    report = anomaly_report(bench_days=bench_days)
    _write(out or OUT_PATH, report)
    for split, block in report["results"].items():
        m = block["metrics"]
        typer.echo(
            f"{split:14} faults {m['faults']} detected {m['detected']} recall {m['recall']:.3f}; "
            f"false alarms {m['false_alarms']} over {m['asset_days']:.1f} asset-days "
            f"({m['fa_per_100_asset_days']:.2f}/100); spoof flagged {m['spoof_flagged']}/{m['spoof_cases']}"
        )
    typer.echo(f"wrote {out or OUT_PATH} at {datetime.now(UTC):%H:%MZ}")
