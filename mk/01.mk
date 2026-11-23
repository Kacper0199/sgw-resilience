.PHONY: check check-quick check-full licences hooks secret-scan image-context

check: ## merge-depth checks: forbidden paths, lint, tests, licences, secrets, test counts vs main
	bash scripts/check.sh merge

check-quick: ## fast checks before a commit (about a minute)
	bash scripts/check.sh quick

check-full: ## quick + slow tests, contracts, policy tests, image context, licences
	bash scripts/check.sh full

licences: ## licence gate over uv.lock and pnpm-lock.yaml (fails on GPL/AGPL/LGPL unless allow-listed)
	uv run --frozen python scripts/licences.py --strict-unknown

hooks: ## install the lefthook git hooks (pre-commit: forbidden paths, secrets, ruff, biome)
	pnpm -C web exec lefthook install

secret-scan: ## gitleaks over history and staged changes (host binary or pinned image)
	bash scripts/secret-scan.sh history
	bash scripts/secret-scan.sh staged

image-context: ## prove the Docker build context excludes private files
	bash scripts/check-image-context.sh
