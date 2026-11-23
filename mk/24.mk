# Water continuity graph and boil-water rules: thin wrappers around `uv run` (K20). Replay only; no key.
.PHONY: rules-test water-graph-test

rules-test: ## Boil-water rules engine (one test per clause) and the PS-17 cross-domain priority rule
	uv run pytest tests/unit/rules -q

water-graph-test: ## water_continuity graph in replay (committed fixtures), M2 parity, clocks, DB drafting
	LLM_MODE=replay uv run pytest tests/unit/agent/test_water_graph.py tests/unit/models/clocks/test_clocks_golden.py -q
