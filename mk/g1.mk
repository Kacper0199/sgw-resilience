# G1 live UI target; it only wraps pnpm (K20: no bash on the user path). Needs `uv run sgw up --demo` and `uv run sgw seed --demo`.
.PHONY: g1
g1: ## G1 live PS-17 story in the browser against the running stack (Vite proxy to :8080)
	pnpm -C web exec playwright test -c e2e/live.config.ts
