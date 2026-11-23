# Gateway completion targets: thin wrappers around `uv run` (K20).
.PHONY: egress-test sec-egress

egress-test: ## Gateway unit tests incl. OPA parity (docker) and the llm_call writer test (Postgres)
	LLM_MODE=replay uv run pytest tests/unit/gateway -q

sec-egress: ## SEC-30 and SEC-33 (restricted classes and canaries never leave the gateway)
	LLM_MODE=replay uv run pytest tests/security/test_sec_30.py tests/security/test_sec_33.py -q
