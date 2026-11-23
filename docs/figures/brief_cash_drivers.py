"""Briefing page 3: what moves the utility cash view, one input at a time.

Source: data/roi/roi_results.json (uv run python -m sgw.roi), tornado on the ten-year cash net present value.
The two drivers that Stage 1 tests (storm restoration cost and build cost) are drawn in the accent colour.
Labels are plain language: the briefing carries no technique names.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("sgw_docs_style", Path(__file__).with_name("style.py"))
style = sys.modules.get("sgw_docs_style") or importlib.util.module_from_spec(_spec)
if "sgw_docs_style" not in sys.modules:
    sys.modules["sgw_docs_style"] = style
    _spec.loader.exec_module(style)

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "data" / "roi" / "roi_results.json"
SHOWN = 8
GATED = {"storm_eff", "build"}


def _pct(v: float) -> str:
    return f"{100 * v:g}%"


LABELS = {
    "storm_cost_per_cust": lambda s: (
        f"SGW storm cost per customer ({s['low']:g} to {s['high']:g} USD a year)"
    ),
    "storm_eff": lambda s: f"Storm restoration cost saved ({_pct(s['low'])} to {_pct(s['high'])})",
    "build": lambda s: f"Build cost ({s['low']:g} to {s['high']:g} M USD once)",
    "vm_eff": lambda s: f"Vegetation work spend saved ({_pct(s['low'])} to {_pct(s['high'])})",
    "cloud": lambda s: f"Cloud and data platform ({s['low']:g} to {s['high']:g} M USD a year)",
    "team_fte": lambda s: f"Platform team ({s['low']:g} to {s['high']:g} people)",
    "fte_released": lambda s: f"Staff time released ({s['low']:g} to {s['high']:g} people)",
    "maint_eff": lambda s: f"Maintenance spend saved ({_pct(s['low'])} to {_pct(s['high'])})",
    "licences": lambda s: f"Licences and data feeds ({s['low']:g} to {s['high']:g} M USD a year)",
    "maint_addressable": lambda s: f"Maintenance open to targeting ({_pct(s['low'])} to {_pct(s['high'])})",
}


def load() -> tuple[float, list[dict]]:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))["tornado"]["npv_cash"]
    return data["base"], data["swings"][:SHOWN]


def build(out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style.apply()
    c = style.colors()
    base, swings = load()
    swings = swings[::-1]
    fig, ax = plt.subplots(figsize=(6.3, 2.1), layout="none")
    fig.subplots_adjust(left=0.43, right=0.98, top=0.9, bottom=0.2)
    ax.grid(False)
    for i, s in enumerate(swings):
        lo, hi = sorted((s["at_low"], s["at_high"]))
        colour = c["secondary"] if s["key"] in GATED else "#A9B4C4"
        ax.barh(i, hi - lo, left=lo, height=0.62, color=colour, linewidth=0)
    ax.axvline(base, color=c["ink"], linewidth=0.9)
    ax.axvline(0, color=c["sev-critical"], linewidth=0.9, linestyle="--")
    ax.text(
        base - 0.6,
        len(swings) - 0.35,
        f"base {base:.1f}",
        ha="right",
        va="bottom",
        fontsize=style.MIN_TEXT_PT,
    )
    ax.text(
        0.6,
        len(swings) - 0.35,
        "break even",
        ha="left",
        va="bottom",
        fontsize=style.MIN_TEXT_PT,
        color=c["sev-critical"],
    )
    ax.set_yticks(range(len(swings)), [LABELS[s["key"]](s) for s in swings])
    ax.set_ylim(-0.6, len(swings) + 0.3)
    ax.set_xlabel("cash net present value over ten years, M USD, one input moved at a time")
    ax.tick_params(axis="y", length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    style.label_footer(
        fig,
        "Dark bars show the two inputs that Stage 1 tests. Model output from assumed inputs (data/roi)",
    )
    paths = style.save(fig, out_dir, "brief_cash_drivers")
    plt.close(fig)
    return paths


if __name__ == "__main__":
    for p in build(REPO / "docs" / "latex" / "shared" / "figures"):
        print(p)
