# Water continuity, WNTR precompute, anomaly guard: thin wrappers around `uv run sgw water` (K20).
SGW ?= uv run sgw

.PHONY: water-precompute water-validate water-ps17 water-survival water-anomaly test-water

water-precompute: ## WNTR drain grid on the host (needs the host dependency group)
	uv run --group host python host/water_twin/precompute.py

water-validate: ## Reduced twin vs the WNTR grid (writes data/artefacts/water_twin/validation.json)
	$(SGW) water validate

water-ps17: ## PS-17 per-member clock table from the twin (writes data/artefacts/water_twin/ps17_clock_members.json)
	$(SGW) water ps17-members

water-survival: ## Station continuity Monte Carlo (generator survival, fuel, drain to the floor)
	$(SGW) water survival

water-anomaly: ## A7/A8 detectors on the helene dev fixture and the dev bench (writes anomaly_dev.json)
	$(SGW) water anomaly

test-water: ## Water twin and anomaly tests
	uv run pytest tests/unit/models/water tests/unit/models/anomaly -q
