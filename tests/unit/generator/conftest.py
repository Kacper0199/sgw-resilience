from __future__ import annotations

from pathlib import Path

import pytest

from sgw.generator.config import Family, load_family, load_scenario
from sgw.generator.scenario import GenerationResult, generate
from sgw.generator.truth import Truth, run_truth


@pytest.fixture(scope="session")
def scenario() -> dict:
    return load_scenario("helene")


@pytest.fixture(scope="session")
def fam_a() -> Family:
    return load_family("A")


@pytest.fixture(scope="session")
def truth(scenario: dict, fam_a: Family) -> Truth:
    return run_truth(scenario, fam_a)


@pytest.fixture(scope="session")
def generated(tmp_path_factory: pytest.TempPathFactory) -> GenerationResult:
    return generate("helene", Path(tmp_path_factory.mktemp("helene_a")))
