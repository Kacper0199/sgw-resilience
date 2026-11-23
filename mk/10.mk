# Web shell targets; they only wrap pnpm (K20: no bash on the user path).
WEB := pnpm -C web

.PHONY: web-dev web-dev-mock web-lint web-typecheck web-test web-build web-e2e-mock web-check
web-dev: ## Vite dev server proxying /api to the compose stack on 127.0.0.1:8080
	$(WEB) exec vite --host 127.0.0.1

web-dev-mock: ## Vite dev server with MSW mocks from the K3/K4 contracts (VITE_MOCK mode)
	$(WEB) exec vite --host 127.0.0.1 --mode mock

web-lint: ## Biome check over web/
	$(WEB) lint

web-typecheck: ## tsc -b over web/
	$(WEB) typecheck

web-test: ## Vitest unit and integration tests
	$(WEB) test

web-build: ## Production bundle into web/dist
	$(WEB) build

web-e2e-mock: ## Playwright thin-slice spec against the MSW mocks
	$(WEB) exec playwright test thin-slice-mock

web-check: web-lint web-typecheck web-test web-build ## The web verify chain without the browser

.PHONY: web-e2e-csp
web-e2e-csp: ## Built app under the Caddy CSP via vite preview
	$(WEB) e2e:csp
