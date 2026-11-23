# RAG targets: thin wrappers around `uv run sgw rag` (K20). Keyless except rag-headers.
.PHONY: rag-corpus rag-check rag-index rag-eval rag-test rag-answer-eval rag-headers

RAG_DB ?= sgw_wp18

rag-corpus: ## Run the record generator, render every document, write data/corpus/MANIFEST.yaml
	uv run sgw rag corpus

rag-check: ## Fail on corpus drift (generated records, rendered text, manifest)
	uv run sgw rag corpus --check

rag-index: ## Load the corpus into Postgres (embedding cache first; fastembed for misses)
	uv run sgw rag index --database $(RAG_DB)

rag-eval: ## Retrieval metrics on the dev split and the development set
	uv run sgw rag eval --database $(RAG_DB) --items evals/dev/retrieval.yaml
	uv run sgw rag eval --database $(RAG_DB) --items tests/unit/agent/rag/data/builder_retrieval.yaml

rag-test: ## Corpus, guard, citation and payload tests; Postgres tests and answer_sop replay (SGW_TEST_DATABASE_URL)
	LLM_MODE=replay uv run pytest tests/unit/agent/rag -q

rag-answer-eval: ## answer_sop on the development questions through a gateway (replay: start one with the RAG fixtures)
	uv run sgw rag answer-eval --database $(RAG_DB) --gateway $${SGW_GATEWAY_URL:-http://127.0.0.1:8100}

rag-headers: ## LIVE: chunk headers for changed chunks via a record-mode gateway (costs money; maintainer only)
	uv run sgw rag headers --gateway $${SGW_GATEWAY_URL:-http://127.0.0.1:8100}
