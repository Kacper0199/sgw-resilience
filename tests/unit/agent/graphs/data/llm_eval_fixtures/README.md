# Eval-only LLM recordings (WP-25)

Recordings from the per-node selection eval (`tests/unit/agent/graphs/report_eval.py`) whose model or prompt
version is not the one `src/sgw/agent/llm_nodes.yaml` sets for the node: Haiku runs of `etr_brief` and
`after_action_summary`, Sonnet runs of `sitrep`, `sitrep` prompt v1, and `sitrep` at the earlier `max_tokens`.
They stay out of `data/fixtures/llm/` because WP-04's replay test replays every runtime fixture under the
production egress rules, which deny these models. `test_report_replay.py` merges both folders into a temporary
replay gateway to regrade the eval keyless. Format: K11 (`docs/gateway.md`).
