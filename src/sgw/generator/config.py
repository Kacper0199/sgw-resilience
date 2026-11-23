"""Generator configuration: family parameter files and scenario files under `data/synthetic/`.

A family file holds labelled parameters (`value` or a `number` key of `data/numbers/numbers.yaml`); a scenario
file holds the storm track, advisory schedule, named assets and seeded cases. Family A and family B carry the
same keys; a family-A run reads only `family_a.yaml`.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from sgw.common import numbers as numbers_mod

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNTHETIC_DIR = REPO_ROOT / "data" / "synthetic"
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
FAMILY_FILES = {"A": "family_a.yaml", "B": "family_b.yaml"}
LABELS = frozenset({"F", "C", "A", "I"})
GENERATOR_NAME = "sgw.generator"
GENERATOR_VERSION = "1.0.0"


class ConfigError(ValueError):
    pass


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


@dataclass(frozen=True)
class Param:
    key: str
    value: Any
    unit: str
    label: str
    source: str


@dataclass(frozen=True)
class Family:
    name: str
    path: Path
    params: dict[str, Param]

    def __getitem__(self, key: str) -> Any:
        try:
            return self.params[key].value
        except KeyError as exc:
            raise ConfigError(f"family {self.name}: unknown parameter {key}") from exc

    def f(self, key: str) -> float:
        return float(self[key])

    def arr(self, key: str) -> np.ndarray:
        return np.asarray(self[key], dtype=float)


def load_family(name: str = "A", directory: Path = SYNTHETIC_DIR) -> Family:
    if name not in FAMILY_FILES:
        raise ConfigError(f"unknown family {name!r}")
    path = directory / FAMILY_FILES[name]
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("family") != name:
        raise ConfigError(f"{path}: family field is {raw.get('family')!r}, expected {name!r}")
    nums = numbers_mod.numbers()
    params: dict[str, Param] = {}
    for key, spec in raw["params"].items():
        if spec.get("label") not in LABELS:
            raise ConfigError(f"{path}: {key} has no valid label")
        if not str(spec.get("source", "")).strip():
            raise ConfigError(f"{path}: {key} has no source")
        if "number" in spec:
            if spec["number"] not in nums:
                raise ConfigError(f"{path}: {key} names unknown numbers.yaml key {spec['number']}")
            value: Any = nums[spec["number"]].value
        elif "value" in spec:
            value = spec["value"]
        else:
            raise ConfigError(f"{path}: {key} has neither value nor number")
        params[key] = Param(key, value, str(spec.get("unit", "")), spec["label"], spec["source"])
    return Family(name=name, path=path, params=params)


@dataclass(frozen=True)
class County:
    fips: str
    name: str
    st: str
    lon: float
    lat: float
    customers: int


def load_counties(path: Path | None = None) -> list[County]:
    path = path or SYNTHETIC_DIR / "footprint_counties.csv"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [
        County(r["fips"].zfill(5), r["name"], r["st"], float(r["lon"]), float(r["lat"]), int(r["customers"]))
        for r in rows
    ]


def load_scenario(name: str, directory: Path = SYNTHETIC_DIR) -> dict[str, Any]:
    path = directory / f"{name}.yaml"
    if not path.is_file():
        raise ConfigError(f"no scenario file {path}")
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("scenario") != name:
        raise ConfigError(f"{path}: scenario field mismatch")
    return data


def stable_ints(*keys: object) -> list[int]:
    digest = hashlib.sha256("\x1f".join(str(k) for k in keys).encode()).digest()
    return [int.from_bytes(digest[i : i + 4], "little") for i in range(0, 16, 4)]


def rng(root_seed: int, *keys: object) -> np.random.Generator:
    """Independent stream per (scenario seed, subsystem, entity, ...), stable across runs and processes."""
    return np.random.default_rng(np.random.SeedSequence([root_seed, *stable_ints(*keys)]))
