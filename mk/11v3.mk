# Outage forecast experiments: thin wrappers around `uv run python -m ...` (K20).
RAW ?= $(shell git rev-parse --path-format=absolute --git-common-dir)/../raw/data

.PHONY: backtest-outage-v3 outage-v3-data test-models-outage-v3

backtest-outage-v3: ## Pre-registered GLM / boosted-residual / wind-calibration LOSO -> evals/reports/outage_loso_v3.json
	uv run sgw models backtest-outage-v3

outage-v3-data: ## Rebuild the v3 derived tables from raw/ (ASOS, static county table, 30-day rain, L2 and gap labels)
	uv run python -m sgw.models.outage.county_static $(RAW)
	uv run python -m sgw.models.hazard.asos $(RAW)/iem_asos/storms
	uv run python -m sgw.models.outage.rain $(RAW)/iem_iemre_ante30 ante30
	uv run python -m sgw.models.outage.labels_v3 $(RAW)/eaglei

test-models-outage-v3: ## Outage forecast v3 unit tests
	uv run pytest tests/unit/models/outage/test_v3.py -q
