# Generator targets: thin wrappers around `uv run sgw data ...` (K20).
SCENARIO ?= helene

.PHONY: data data-verify data-calibrate test-generator

data: ## Generate the synthetic scenario SCENARIO (default helene) into data/fixtures/SCENARIO
	uv run sgw data generate --scenario $(SCENARIO)

data-verify: ## Check data/fixtures/SCENARIO against its manifest
	uv run sgw data verify --scenario $(SCENARIO)

data-calibrate: ## Re-run the repair-scale calibration to the Helene t50
	uv run sgw data calibrate --scenario $(SCENARIO)

test-generator: ## Generator unit tests
	uv run pytest tests/unit/generator -q
