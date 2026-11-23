# Outage-surge detector (G1): thin wrappers around `uv run python -m ...` (K20).
RAW ?= $(shell git rev-parse --path-format=absolute --git-common-dir)/../raw/data

.PHONY: surge-fit test-models-surge

surge-fit: ## G1: train-only grid search 2016-2021, test 2022-2025 -> evals/reports/outage_surge.json, data/artefacts/surge/
	uv run python -m sgw.models.surge.fit --raw-dir $(RAW)

test-models-surge: ## G1 unit and regression tests
	uv run pytest tests/unit/models/surge -q
