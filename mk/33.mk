# Demo journeys: bookmarks and the demo smoke; the targets only wrap the CLI (K20).
.PHONY: demo-smoke demo-build demo-bookmarks
demo-smoke: ## Ten PS-17 story steps on a scratch DB + private replay stack, replay hit rate, K19 playback (out/demo-smoke.json)
	uv run sgw demo smoke
demo-build: ## Build the PS-17 bookmarks (template databases) and K19 event logs from one story run
	uv run sgw demo build
demo-bookmarks: ## List the PS-17 bookmarks and whether each is built; restore one with `uv run sgw demo goto <id>`
	uv run sgw demo list
