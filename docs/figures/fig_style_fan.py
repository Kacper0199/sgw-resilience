"""Style reference chart: a forecast with nested 50/80/95% fans on synthetic data.

It proves the shared style (palette, fonts, fans, units, label footer) before real
evaluation data exist. Later figures follow the same pattern: build(out_dir) -> paths.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

_spec = importlib.util.spec_from_file_location("sgw_docs_style", Path(__file__).with_name("style.py"))
style = sys.modules.get("sgw_docs_style") or importlib.util.module_from_spec(_spec)
if "sgw_docs_style" not in sys.modules:
    sys.modules["sgw_docs_style"] = style
    _spec.loader.exec_module(style)

SEED = 17


def synthetic_series() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(SEED)
    hours = np.arange(-24, 97, 3)
    peak = 1.0 / (1.0 + np.exp(-(hours - 6) / 4.0))
    decay = np.exp(-np.clip(hours - 18, 0, None) / 40.0)
    median = 100.0 * peak * decay
    spread = 4.0 + 0.22 * np.clip(hours, 0, None)
    observed = np.clip(median + rng.normal(0, 3.0, size=hours.size), 0, None)
    observed[hours > 12] = np.nan
    return hours, median, spread, observed


def build(out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style.apply()
    c = style.colors()
    hours, median, spread, observed = synthetic_series()
    fig, ax = plt.subplots(figsize=(6.0, 2.6))
    for level, z in ((95, 1.96), (80, 1.28), (50, 0.67)):
        ax.fill_between(
            hours,
            np.clip(median - z * spread, 0, None),
            median + z * spread,
            color=c["secondary"],
            alpha=style.FAN_ALPHAS[level],
            linewidth=0,
            label=f"{level}% range",
        )
    ax.plot(hours, median, color=c["secondary"], label="median forecast")
    ax.plot(hours, observed, color=c["primary"], marker="o", markersize=2.5, linewidth=1.0, label="observed")
    ax.axvline(0, color=c["sev-critical"], linewidth=0.9)
    ax.text(
        0.8,
        ax.get_ylim()[1] * 0.95,
        "landfall",
        color=c["sev-critical"],
        fontsize=style.MIN_TEXT_PT,
        va="top",
    )
    ax.set_xlabel("hours from landfall (h)")
    ax.set_ylabel("customers out (% of peak)")
    ax.set_title("Outage forecast with nested ranges", loc="left")
    ax.legend(loc="upper right", ncols=2)
    style.label_footer(fig, "synthetic data, style reference only")
    paths = style.save(fig, out_dir, "style_fan")
    plt.close(fig)
    return paths


if __name__ == "__main__":
    for p in build(Path(__file__).resolve().parents[1] / "latex" / "shared" / "figures"):
        print(p)
