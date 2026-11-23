# Held-out evaluation material: thin wrappers (stdlib manifest script, generator CLI; K20).
.PHONY: evals-check evals-manifest evals-family-b test-evals-heldout

evals-check: ## Check evals/MANIFEST.sha256 against every held-out and family-B file
	uv run python evals/manifest.py check

evals-manifest: ## Regenerate evals/MANIFEST.sha256 (eval author only)
	uv run python evals/manifest.py write

evals-family-b: ## Generate the family-B scenario into var/family_b (held out; never train on it)
	uv run sgw data generate --scenario family_b/debby_b --out var/family_b

test-evals-heldout: ## Held-out manifest, counts and item validity
	uv run pytest tests/contracts/test_heldout_manifest.py -q
