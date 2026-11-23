# After-action and Admin targets; they only wrap pnpm (K20: no bash on the user path).
.PHONY: web-e2e-afteraction-admin
web-e2e-afteraction-admin: ## Playwright specs for After-action and Admin against the MSW mocks (port 64500)
	pnpm -C web exec playwright test -c e2e/after-action-admin.config.ts
