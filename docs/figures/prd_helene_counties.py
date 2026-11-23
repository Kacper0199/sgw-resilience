"""PRD Figure 1: Helene restoration across the footprint counties, real EAGLE-I data.

Source: data/synthetic/validation/helene_eaglei_county.csv (EAGLE-I, ORNL, CC BY 4.0), one row per
footprint county with the share of customers out at the county peak and the hours from onset to 90%
restored. Counties whose outage never reached 90% restored inside the file window are drawn at the
window edge and hatched.
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("sgw_docs_style", Path(__file__).with_name("style.py"))
style = sys.modules.get("sgw_docs_style") or importlib.util.module_from_spec(_spec)
if "sgw_docs_style" not in sys.modules:
    sys.modules["sgw_docs_style"] = style
    _spec.loader.exec_module(style)

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "data" / "synthetic" / "validation" / "helene_eaglei_county.csv"
STATE_BY_FIPS_PREFIX = {"45": "South Carolina", "13": "Georgia (east)"}
MIN_PEAK_SHARE = 0.10


def load_rows(path: Path = SOURCE) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            share = float(r["peak_frac"])
            if share < MIN_PEAK_SHARE:
                continue
            t90 = float(r["t90_h"]) if r["t90_h"] else None
            rows.append({"state": STATE_BY_FIPS_PREFIX[r["fips"][:2]], "share": share, "t90": t90})
    return rows


def build(out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    style.apply()
    c = style.colors()
    rows = load_rows()
    window = max(r["t90"] for r in rows if r["t90"] is not None)
    rows.sort(key=lambda r: -(r["t90"] if r["t90"] is not None else window + 1))
    hours = np.array([r["t90"] if r["t90"] is not None else window for r in rows]) / 24.0
    colour = {"South Carolina": c["secondary"], "Georgia (east)": "#9DB0C9"}

    fig, ax = plt.subplots(figsize=(6.3, 2.05))
    x = np.arange(len(rows))
    for state, col in colour.items():
        idx = [i for i, r in enumerate(rows) if r["state"] == state]
        ax.bar(x[idx], hours[idx], width=0.85, color=col, label=state, linewidth=0)
    open_idx = [i for i, r in enumerate(rows) if r["t90"] is None]
    if open_idx:
        ax.bar(
            x[open_idx],
            hours[open_idx],
            width=0.85,
            color="none",
            edgecolor=c["sev-critical"],
            hatch="////",
            linewidth=0.4,
            label="not 90% restored in the data window",
        )
    median_days = float(np.median(hours))
    ax.axhline(median_days, color=c["ink"], linewidth=0.8, linestyle="--")
    ax.text(
        len(rows) - 1,
        median_days,
        f"median {median_days:.1f} days",
        ha="right",
        va="bottom",
        fontsize=style.MIN_TEXT_PT,
    )
    ax.set_xlim(-0.8, len(rows) - 0.2)
    ax.set_xticks([])
    ax.set_xlabel(
        f"footprint counties with at least {MIN_PEAK_SHARE:.0%} of customers out at peak "
        f"(n = {len(rows)}), slowest first"
    )
    ax.set_ylabel("days from onset\nto 90% restored")
    ax.legend(loc="upper right", ncols=3)
    style.label_footer(fig, "Real data from EAGLE-I county outages, Hurricane Helene 2024 (ORNL, CC BY 4.0)")
    paths = style.save(fig, out_dir, "prd_helene_counties")
    plt.close(fig)
    return paths


if __name__ == "__main__":
    for p in build(REPO / "docs" / "latex" / "shared" / "figures"):
        print(p)
