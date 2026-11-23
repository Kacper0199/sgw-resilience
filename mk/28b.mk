# Health and Readiness web targets; they only wrap pnpm (K20: no bash on the user path).
.PHONY: web-e2e-health
web-e2e-health: ## Playwright specs for Health and Readiness against the MSW mocks (port 62800)
	pnpm -C web exec playwright test -c e2e/health.config.ts
