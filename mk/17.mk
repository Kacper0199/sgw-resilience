# Restoration process and ETR (A6): thin wrappers around `uv run sgw restoration ...` (K20).
SGW ?= uv run sgw
ETR_HOURS ?= 24
ETR_DB ?=

.PHONY: restoration-calibrate etr-eval etr test-restoration

restoration-calibrate: ## Fit the restoration process to the EAGLE-I Helene county t50/t90 (about 15 min)
	$(SGW) restoration calibrate

etr-eval: ## Helene calibration report + family-A ETR coverage -> evals/reports/etr.json (about 15 min, 2 workers)
	$(SGW) restoration eval

etr: ## Global and regional ETR P10..P90 for the Helene story (ETR_HOURS after the peak; ETR_DB=<db> to store)
	$(SGW) restoration etr --hours-after-peak $(ETR_HOURS) $(if $(ETR_DB),--database $(ETR_DB))

test-restoration: ## Restoration unit tests
	uv run pytest tests/unit/models/restoration -q
