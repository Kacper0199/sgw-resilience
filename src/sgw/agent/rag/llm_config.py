"""Where the WP-18 node rows live (K14 schema) and the K11 fixture folder of the corpus LLM calls."""

from __future__ import annotations

from pathlib import Path

from sgw.agent.rag.corpus import CORPUS_DIR

RAG_NODES_FILE = Path(__file__).resolve().parent / "llm_nodes.rag.yaml"
RAG_FIXTURES = CORPUS_DIR / "llm_fixtures"
