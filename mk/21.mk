# Targets: extractor N2, route_intent N1, copilot N4. Thin wrappers around `uv run` (K20). Keyless
# except the *-eval-live targets, which need a record-mode gateway (costs money; maintainer only).
.PHONY: copilot-test copilot-sec copilot-eval-replay extract-eval-live route-eval-live copilot-eval-live

WP21_EVAL_NODES := tests/unit/agent/extract/data/eval_nodes.yaml

copilot-test: ## N1/N2/N4 unit, replay and DB tests (DB tests need SGW_TEST_DATABASE_URL)
	LLM_MODE=replay uv run pytest tests/unit/agent/extract tests/unit/agent/route tests/unit/agent/copilot -q

copilot-sec: ## SEC-02/03/06/08/13/34 for the extractor and the copilot
	LLM_MODE=replay uv run pytest tests/security/test_sec_02.py tests/security/test_sec_03.py tests/security/test_sec_06.py tests/security/test_sec_08.py tests/security/test_sec_13.py tests/security/test_sec_34.py -q

copilot-eval-replay: ## Rerun the three selection evals keyless from the committed recordings
	LLM_MODE=replay uv run pytest tests/unit/agent/extract/test_extract_eval_replay.py tests/unit/agent/route/test_route_intent.py tests/unit/agent/copilot/test_copilot_eval_replay.py -q

extract-eval-live: ## LIVE: N2 Sonnet vs Haiku on the dev items via $$SGW_GATEWAY_URL (record mode, eval node rules)
	uv run python -m sgw.agent.extract.evaluate --gateway $${SGW_GATEWAY_URL:?} --models sonnet,haiku --out data/artefacts/evals/wp21_extract_eval_v2.json

route-eval-live: ## LIVE: N1 Sonnet vs Haiku on the development set
	uv run python -m sgw.agent.route.evaluate --gateway $${SGW_GATEWAY_URL:?} --models sonnet,haiku --out data/artefacts/evals/wp21_route_eval_v1.json

copilot-eval-live: ## LIVE: copilot dev eval with live search (SGW_DATABASE_URL) and search recording
	uv run python -m sgw.agent.copilot.evaluate --gateway $${SGW_GATEWAY_URL:?} --live-search --out data/artefacts/evals/copilot_eval_v4.json
