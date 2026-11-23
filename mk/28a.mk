# Ops API and control plane: thin wrappers around the ops CLI (K20), `sgw ops`.
SGW_28A ?= uv run sgw ops
OPS_DB ?= sgw

.PHONY: ops-status ops-reconcile ops-drill-llm-down ops-rules test-ops
ops-status: ## Kill level, degraded mode, active signals and capabilities of OPS_DB
	$(SGW_28A) status --database $(OPS_DB)

ops-reconcile: ## Apply FAULT_* flags and configured probes to OPS_DB once
	$(SGW_28A) reconcile --database $(OPS_DB)

ops-drill-llm-down: ## Drill: FAULT_LLM_DOWN=1 moves OPS_DB to M2 (run ops-reconcile afterwards to leave it)
	FAULT_LLM_DOWN=1 $(SGW_28A) reconcile --database $(OPS_DB)

ops-rules: ## Mode ladder, signal table (entry, behaviour, exit) and kill-level capability matrix
	$(SGW_28A) rules

test-ops: ## Ops API unit, database and SEC-60/63/70/73 tests
	uv run pytest tests/unit/ops tests/security/test_sec_60.py tests/security/test_sec_63.py tests/security/test_sec_70.py tests/security/test_sec_73.py -n 2
