# Audit chain, break-glass and envelope targets: thin wrappers around `uv run sgw audit ...` (K20).
SGW_09B ?= uv run sgw
AUDIT_DB ?= sgw

.PHONY: audit-keygen audit-checkpoint audit-verify audit-cosign-tasks audit-policy-data test-audit
audit-keygen: ## Create (or rotate to) an Ed25519 audit signing key under var/secrets/audit (0600)
	$(SGW_09B) audit keygen --database $(AUDIT_DB)

audit-checkpoint: ## Sign the audit head of AUDIT_DB and write the anchor file
	$(SGW_09B) audit checkpoint --database $(AUDIT_DB)

audit-verify: ## Verify the audit chain, checkpoints and anchors of AUDIT_DB (exit 1 with the first bad seq)
	$(SGW_09B) audit verify --database $(AUDIT_DB)

audit-cosign-tasks: ## List open break-glass co-sign tasks of AUDIT_DB
	$(SGW_09B) audit cosign-tasks --database $(AUDIT_DB)

audit-policy-data: ## Regenerate policy/sgw/governance/data.json
	$(SGW_09B) audit policy-data

test-audit: ## Audit, break-glass, envelope and SEC-52 tests (DB tests need the stack, OPA tests docker)
	uv run pytest tests/unit/approval/test_audit.py tests/unit/approval/test_breakglass.py tests/unit/approval/test_envelope.py tests/security/test_sec_52.py -q
