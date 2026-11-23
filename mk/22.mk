# Scenario-lite: thin wrappers around `uv run sgw scenarios` (K20).
SCENARIOS ?= uv run sgw scenarios
SCENARIO ?= all

.PHONY: scenarios scenarios-check scenarios-whatif test-scenarios

scenarios: ## Generate blue-sky/Readiness, Table Rock and heat fixtures (SCENARIO=bluesky|tablerock|heat|all)
	$(SCENARIOS) generate $(SCENARIO)

scenarios-check: ## Regenerate twice into temp folders; fail unless both match the committed manifests
	$(SCENARIOS) check $(SCENARIO)

scenarios-whatif: ## Rebuild the precomputed Helene what-if grid (81 truth runs, about 2 min)
	$(SCENARIOS) whatif

test-scenarios: ## Wildfire, heat, what-if and scenario fixture tests
	uv run pytest tests/unit/models/wildfire tests/unit/models/heat tests/unit/models/whatif tests/unit/generator/scenarios -q
