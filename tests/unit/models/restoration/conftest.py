from __future__ import annotations

import pytest

from sgw.models.restoration.etr import EtrModel, fit_model
from sgw.models.restoration.evaluate import storm_run
from sgw.models.restoration.params import default_params
from sgw.models.restoration.process import ProcessRun, simulate
from sgw.models.restoration.world import family_a_world, story_seed

TRAIN_SEEDS = (1000, 1001)
TEST_SEED = 3000


@pytest.fixture(scope="session")
def story() -> ProcessRun:
    return simulate(family_a_world(story_seed()), default_params())


@pytest.fixture(scope="session")
def small_model() -> EtrModel:
    prm = default_params()
    return fit_model([storm_run(s, prm) for s in TRAIN_SEEDS], prm)


@pytest.fixture(scope="session")
def test_storm() -> ProcessRun:
    return storm_run(TEST_SEED, default_params())
