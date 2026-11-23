# Hazard ensemble and outage forecast targets: thin wrappers around `uv run sgw models ...` (K20).
ADVISORY ?= N+1
DATABASE ?= sgw_wp11

.PHONY: backtest-outage backtest-outage-v2 hazard-check outage-risk plan-diff no-regret publish-risk test-models-outage

backtest-outage: ## Outage LOSO on 4 real storms beside the wind-threshold baseline -> evals/reports/outage_loso.json
	uv run sgw models backtest-outage

backtest-outage-v2: ## 24-storm LOSO, pre-registered variants, nested selection -> evals/reports/outage_loso_v2.json
	uv run sgw models backtest-outage-v2

hazard-check: ## A1 ensemble spread vs observed ASOS peak gusts at advisory ADVISORY
	uv run sgw models hazard-check --advisory $(ADVISORY)

outage-risk: ## County fans, top assets and no-regret shares of one advisory (ADVISORY=N+1)
	uv run sgw models risk --advisory $(ADVISORY)

plan-diff: ## Plan diff between advisories N and N+1
	uv run sgw models plan-diff --from N --to N+1

no-regret: ## No-regret share per action across ensemble members (ADVISORY=N+1)
	uv run sgw models no-regret --advisory $(ADVISORY)

publish-risk: ## Publish RiskSnapshotPublished on every scenario tick (DATABASE=sgw_wp11)
	uv run sgw models publish-risk --database $(DATABASE) --follow

test-models-outage: ## Outage forecast unit tests
	uv run pytest tests/unit/models/hazard tests/unit/models/outage -q
