"""Shared plumbing for the second-tier scenarios: the WP-06 synthetic world, deterministic writers, K9 headers
and per-folder manifests (sha256 per file plus a combined hash, so two runs can be compared byte for byte)."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from sgw.contracts.events import EnvelopeBase
from sgw.contracts.fixtures import FixtureHeader, write_fixture
from sgw.generator.config import Family, load_counties, load_family, load_scenario
from sgw.generator.emit import EventSink
from sgw.generator.network import Network, build_network
from sgw.generator.scenarios.weather import FIXTURES
from sgw.generator.wind import epoch

GENERATOR = "sgw.generator.scenarios"
GENERATOR_VERSION = "1.0.0"
WORLD_SCENARIO = "helene"
ASOS_SOURCE = (
    "Iowa Environmental Mesonet ASOS archive (https://mesonet.agron.iastate.edu/request/download.phtml), "
    "public METAR observations (NWS/FAA), accessed 2026-11-19"
)
LICENCE = (
    "Apache-2.0 (synthetic data). Inputs: ASOS station observations (public METAR, NWS/FAA via IEM); "
    "county customer counts EAGLE-I MCC (CC BY 4.0, ORNL, doi:10.6084/m9.figshare.24237376.v4)"
)


@cache
def world() -> tuple[dict[str, Any], Family, Network]:
    """The WP-06 synthetic network (family A, Helene world seed), so feeders and named assets are the same ids
    as on the golden path."""
    sc = load_scenario(WORLD_SCENARIO)
    fam = load_family(sc["family"])
    return sc, fam, build_network(load_counties(), fam, sc, int(sc["seed"]))


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def r(x: float, nd: int = 4) -> float:
    return float(round(x, nd))


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )


def sink(scenario: str, start: datetime, end: datetime) -> EventSink:
    _, fam, _ = world()
    return EventSink(scenario, fam, (epoch(start), epoch(end)))


def write_feed(
    out: Path,
    scenario: str,
    feed: str,
    events: list[EnvelopeBase],
    start: datetime,
    end: datetime,
    *,
    calibration_source: str,
    note: str,
    data_label: str = "mixed",
) -> FixtureHeader:
    sc, _, _ = world()
    header = {
        "fixture": scenario,
        "schema_version": 1,
        "feed": feed,
        "feed_mode": "synthetic",
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "seed": int(sc["seed"]),
        "calibration_source": calibration_source,
        "scenario_window": {"start_utc": iso(start), "end_utc": iso(end)},
        "licence": LICENCE,
        "hand_made": False,
        "data_label": data_label,
        "note": note,
    }
    return write_fixture(out / f"{feed}.jsonl", header, events)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(
    out: Path, scenario: str, outputs: Sequence[str], inputs: Sequence[Path]
) -> dict[str, Any]:
    files = {n: {"sha256": sha256_file(out / n)} for n in sorted(outputs)}
    combined = hashlib.sha256(
        "".join(f"{k}:{files[k]['sha256']}\n" for k in sorted(files)).encode()
    ).hexdigest()
    manifest = {
        "scenario": scenario,
        "generator": GENERATOR,
        "generator_version": GENERATOR_VERSION,
        "inputs": {p.name: {"sha256": sha256_file(p)} for p in sorted(inputs, key=lambda x: x.name)},
        "files": files,
        "combined_sha256": combined,
        "label": "synthetic outputs; weather inputs are real ASOS observations",
    }
    write_json(out / "manifest.json", manifest)
    return manifest


def fixtures_dir(name: str, root: Path | None = None) -> Path:
    return (root or FIXTURES) / name
