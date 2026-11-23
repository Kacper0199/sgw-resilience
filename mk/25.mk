# Report graphs (etr, sitrep, after_action): thin wrappers around `uv run` (K20). Replay only; no key.
.PHONY: reports-test reports-replay reports-eval-replay

reports-test: ## ETR, sitrep and after-action graphs, SC 103-314 draft, audit-chain review (DB tests need SGW_TEST_DATABASE_URL)
	LLM_MODE=replay uv run pytest tests/unit/reports tests/unit/agent/graphs -q

reports-replay: ## The three graphs on the replay gateway with the committed recordings, and the M2 path
	LLM_MODE=replay uv run pytest tests/unit/agent/graphs/test_report_replay.py -q

reports-eval-replay: ## Per-node selection eval rerun from the recordings (start a replay gateway allowing sonnet and haiku first)
	uv run python -m tests.unit.agent.graphs.report_eval --gateway $${SGW_GATEWAY_URL:-http://127.0.0.1:8100} --purpose test --models sonnet haiku --out /dev/null
