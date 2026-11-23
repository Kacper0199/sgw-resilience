# Ask and Brief UI targets; they only wrap pnpm (K20: no bash on the user path).
.PHONY: web-e2e-ask-brief
web-e2e-ask-brief: ## Ask and Brief Playwright specs against the MSW mocks (port 62700)
	pnpm -C web exec playwright test -c e2e/ask-brief.config.ts
