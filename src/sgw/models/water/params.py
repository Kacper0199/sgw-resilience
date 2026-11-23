"""Twin parameters: `water_twin.yaml` (labelled), plant data from the generator family and scenario."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from sgw.generator.config import Family, load_family, load_scenario

PARAMS_PATH = Path(__file__).with_name("water_twin.yaml")
REPO_ROOT = Path(__file__).resolve().parents[4]
ARTEFACT_DIR = REPO_ROOT / "data" / "artefacts" / "water_twin"


class TwinParamError(KeyError):
    pass


@dataclass(frozen=True)
class TwinParams:
    version: str
    model_ids: dict[str, str]
    raw: dict[str, dict[str, Any]]

    def __getitem__(self, key: str) -> Any:
        try:
            return self.raw[key]["value"]
        except KeyError as exc:
            raise TwinParamError(f"water_twin.yaml: unknown parameter {key}") from exc

    def f(self, key: str) -> float:
        return float(self[key])

    def label(self, key: str) -> str:
        return str(self.raw[key]["label"])


@cache
def twin_params(path: Path = PARAMS_PATH) -> TwinParams:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, entry in data["params"].items():
        missing = {"value", "unit", "label", "source"} - set(entry)
        if missing:
            raise TwinParamError(f"{key}: missing {sorted(missing)}")
    return TwinParams(version=str(data["version"]), model_ids=dict(data["model_ids"]), raw=data["params"])


@cache
def scenario(name: str = "helene") -> dict[str, Any]:
    return load_scenario(name)


@cache
def family(name: str = "A") -> Family:
    return load_family(name)
