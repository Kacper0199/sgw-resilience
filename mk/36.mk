# CV damage triage (O-06): LADI-v2 reference scores precomputed on the host, review queue from the scores.
SGW_PY ?= uv run python
CV_TRANSFORMERS ?= transformers==5.23.0

.PHONY: cv-fetch cv-score cv-queue cv-verify test-cv

cv-fetch: ## Download the 200 LADI-v2 sample images into var/cv (sha256 checked)
	$(SGW_PY) host/cv/ladi_fetch.py fetch

cv-score: ## Score the sample on MPS (host group + transformers)
	uv run --group host --with '$(CV_TRANSFORMERS)' python host/cv/ladi_score.py

cv-queue: ## Build the review queue from the committed scores (no torch)
	$(SGW_PY) -m sgw.models.cv build

cv-verify: ## Check the manifest hashes and that the queue orders the seeded damage cases
	$(SGW_PY) -m sgw.models.cv verify

test-cv: ## CV damage-triage tests
	uv run pytest tests/unit/models/test_cv_queue.py -q
