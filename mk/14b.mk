# Agent spine targets: thin wrappers around `uv run` (K20). Replay only; no key, no live calls.
.PHONY: agent-test sec-agent agent-eval-replay

agent-test: ## Agent spine: render/verify, assess graph in replay, M2 path, runs router
	LLM_MODE=replay uv run pytest tests/unit/agent -q

sec-agent: ## SEC-01, SEC-14, SEC-39 (hostile note, hostile tool request, invented ids and numbers)
	LLM_MODE=replay uv run pytest tests/security/test_sec_01.py tests/security/test_sec_14.py tests/security/test_sec_39.py -q

agent-eval-replay: ## Per-node selection eval rerun from the committed recordings (start a replay gateway first)
	uv run python -m tests.unit.agent.node_eval --gateway $${SGW_GATEWAY_URL:-http://127.0.0.1:8100} --purpose test --models sonnet
