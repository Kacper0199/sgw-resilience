"""HURDAT2 best tracks of the real storms of the outage backtest (A1 input).

`STORMS` are the four WP-11 storms. `EXTENDED_STORMS` is every Atlantic storm 2016-2025 whose centre
came within 100 km of a footprint county centroid at >= 34 kt, the rule fixed before any outage data was read.

Rows use the layout of the generator scenario files, so `sgw.generator.wind.Track.from_rows` reads both:
`[time_utc, lat, lon, vmax_kt, pmin_hpa, rmw_nmi, r34_ne, r34_se, r34_sw, r34_nw]` (radii in n mi).
HURDAT2 has no radius of maximum wind before 2021 (-999); those fixes get the Willoughby and Rahn (2004)
climatology RMW = 46.4 exp(-0.0155 Vmax + 0.0169 lat) km (label A), recorded per row in `rmw_source`.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sgw.generator.config import parse_utc
from sgw.generator.wind import KT, NMI_KM, Track

REPO_ROOT = Path(__file__).resolve().parents[4]
OPEN_DIR = REPO_ROOT / "data" / "open" / "eaglei"
TRACKS_CSV = OPEN_DIR / "storm_tracks.csv"
TRACK_COLUMNS = (
    "storm",
    "atcf_id",
    "time_utc",
    "lat",
    "lon",
    "vmax_kt",
    "pmin_hpa",
    "rmw_nmi",
    "r34_ne_nmi",
    "r34_se_nmi",
    "r34_sw_nmi",
    "r34_nw_nmi",
    "rmw_source",
)


@dataclass(frozen=True)
class Storm:
    name: str
    atcf_id: str
    year: int


STORMS: tuple[Storm, ...] = (
    Storm("michael", "AL142018", 2018),
    Storm("ian", "AL092022", 2022),
    Storm("debby", "AL042024", 2024),
    Storm("helene", "AL092024", 2024),
)
EXTENDED_STORMS: tuple[Storm, ...] = (
    Storm("colin_2016", "AL032016", 2016),
    Storm("hermine", "AL092016", 2016),
    Storm("julia", "AL112016", 2016),
    Storm("matthew", "AL142016", 2016),
    Storm("irma", "AL112017", 2017),
    Storm("florence", "AL062018", 2018),
    Storm("michael", "AL142018", 2018),
    Storm("dorian", "AL052019", 2019),
    Storm("nestor", "AL162019", 2019),
    Storm("bertha", "AL022020", 2020),
    Storm("isaias", "AL092020", 2020),
    Storm("zeta", "AL282020", 2020),
    Storm("eta", "AL292020", 2020),
    Storm("claudette", "AL032021", 2021),
    Storm("danny", "AL042021", 2021),
    Storm("elsa", "AL052021", 2021),
    Storm("mindy", "AL132021", 2021),
    Storm("colin_2022", "AL032022", 2022),
    Storm("ian", "AL092022", 2022),
    Storm("nicole", "AL172022", 2022),
    Storm("idalia", "AL102023", 2023),
    Storm("debby", "AL042024", 2024),
    Storm("helene", "AL092024", 2024),
    Storm("chantal", "AL032025", 2025),
)
STORM_BY_NAME = {s.name: s for s in EXTENDED_STORMS}


def climatology_rmw_nmi(vmax_kt: float, lat: float) -> float:
    rmw_km = 46.4 * math.exp(-0.0155 * vmax_kt * KT + 0.0169 * abs(lat))
    return rmw_km / NMI_KM


def _coord(text: str) -> float:
    text = text.strip()
    value = float(text[:-1])
    return -value if text[-1] in "SW" else value


def parse_hurdat2(path: Path, atcf_ids: set[str]) -> dict[str, list[dict[str, object]]]:
    """Fixes of the wanted storms as dict rows (TRACK_COLUMNS without `storm`)."""
    out: dict[str, list[dict[str, object]]] = {}
    current: str | None = None
    remaining = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            parts = [p.strip() for p in line.split(",")]
            if remaining == 0:
                current = parts[0] if parts[0] in atcf_ids else None
                remaining = int(parts[2])
                if current:
                    out[current] = []
                continue
            remaining -= 1
            if current is None:
                continue
            t = datetime.strptime(parts[0] + parts[1], "%Y%m%d%H%M").replace(tzinfo=UTC)
            lat, lon, vmax = _coord(parts[4]), _coord(parts[5]), float(parts[6])
            rmw_raw = float(parts[20]) if len(parts) > 20 and parts[20] else -999.0
            rmw_source = "hurdat2"
            if rmw_raw < 0:
                rmw_raw = climatology_rmw_nmi(vmax, lat)
                rmw_source = "willoughby_rahn_2004"
            out[current].append(
                {
                    "atcf_id": current,
                    "time_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "lat": lat,
                    "lon": lon,
                    "vmax_kt": vmax,
                    "pmin_hpa": float(parts[7]),
                    "rmw_nmi": round(rmw_raw, 1),
                    "r34_ne_nmi": max(float(parts[8]), 0.0),
                    "r34_se_nmi": max(float(parts[9]), 0.0),
                    "r34_sw_nmi": max(float(parts[10]), 0.0),
                    "r34_nw_nmi": max(float(parts[11]), 0.0),
                    "rmw_source": rmw_source,
                }
            )
    missing = atcf_ids - set(out)
    if missing:
        raise ValueError(f"storms not in {path.name}: {sorted(missing)}")
    return out


def write_tracks(
    hurdat2_path: Path, out_path: Path = TRACKS_CSV, storms: tuple[Storm, ...] = EXTENDED_STORMS
) -> int:
    parsed = parse_hurdat2(hurdat2_path, {s.atcf_id for s in storms})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRACK_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for storm in storms:
            for row in parsed[storm.atcf_id]:
                writer.writerow({"storm": storm.name, **row})
                n += 1
    return n


def track_rows(storm: str, path: Path = TRACKS_CSV) -> list[list[object]]:
    with path.open(encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["storm"] == storm]
    if not rows:
        raise KeyError(f"no track rows for storm {storm!r} in {path}")
    return [
        [
            r["time_utc"],
            float(r["lat"]),
            float(r["lon"]),
            float(r["vmax_kt"]),
            float(r["pmin_hpa"]),
            float(r["rmw_nmi"]),
            float(r["r34_ne_nmi"]),
            float(r["r34_se_nmi"]),
            float(r["r34_sw_nmi"]),
            float(r["r34_nw_nmi"]),
        ]
        for r in rows
    ]


def load_track(storm: str, path: Path = TRACKS_CSV) -> Track:
    return Track.from_rows(track_rows(storm, path), parse_utc)
