# Map and Forecast targets; they only wrap pnpm and uv.
.PHONY: web-e2e-map-forecast wp20-fixtures
web-e2e-map-forecast: ## Map and Forecast Playwright specs on port 62000 against the MSW mocks
	pnpm -C web exec playwright test -c e2e/wp20.config.ts

wp20-fixtures: ## Regenerate the Map and Forecast MSW fixtures from the repository's own outputs
	uv run --frozen python web/scripts/build_wp20_fixtures.py
