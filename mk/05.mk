# Documents. Every target wraps docs/build.py, which runs on any OS with uv and TeX Live.
DOCS_BUILD := uv run python docs/build.py

.PHONY: docs docs-prd docs-briefing docs-diagrams docs-figures docs-lint docs-final docs-test

docs: ## Build PRD, briefing and diagrams (draft), lint, check page budgets
	$(DOCS_BUILD) all

docs-prd: ## Build the PRD only
	$(DOCS_BUILD) prd

docs-briefing: ## Build the executive briefing only
	$(DOCS_BUILD) briefing

docs-diagrams: ## Render each TikZ diagram to docs/pdf/diagrams with a 60 dpi preview
	$(DOCS_BUILD) diagrams

docs-figures: ## Regenerate Matplotlib figures from docs/figures/fig_*.py
	$(DOCS_BUILD) figures

docs-lint: ## Prose lint, plain-language lexicon and palette drift check (no TeX)
	$(DOCS_BUILD) lint

docs-final: ## Final build: fails on stub numbers, unknown keys and pending boxes
	$(DOCS_BUILD) all --final

docs-test: ## Unit tests of the prose lint
	uv run pytest docs/latex/lint -q
