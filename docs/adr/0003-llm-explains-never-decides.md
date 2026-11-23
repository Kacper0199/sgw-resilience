# ADR 0003: The LLM explains, never decides: slots and a verifier

Status: Accepted (2026-11-19)

## Context

Language models write good explanations and occasionally wrong numbers. In an emergency operations centre a plausible wrong time ("decide by 05:15") is worse than no text. Grounding by prompt alone ("only use the numbers provided") reduces errors but does not prove their absence.

## Decision

- Models predict, deterministic code computes, and the LLM only explains.
- LLM nodes receive an **evidence view** (contract K15): ids, kinds, labels, bands, units and slot names, but no values. The model writes slots such as `{E3.decide_by_p50}`; code fills them (`src/sgw/agent/render/slots.py`).
- The **verifier** (`src/sgw/agent/render/verify.py`) rejects text where any digit-bearing token outside a slot is not an exact id from the run's evidence or the asset and document registry, or where it finds a number word, a non-ASCII numeral, a link, markup or a sentence that claims authority ("approved", "go ahead"). Shape alone never passes: an invented `PS-91` fails.
- On a verifier failure, a gateway failure, a refusal or any tool-use attempt, the node falls back to a **template** (mode M2) filled with the same slot values. The operator sees the same numbers either way.
- Retrieved and free-text inputs pass a guard first (`src/sgw/agent/rag/guard.py`, `src/sgw/agent/extract/guard.py`). The copilot has read-only tools only.

## Alternatives considered

- **Free text with a post-hoc number check.** Compares numbers in the text with known values; misses rounding, unit changes and invented ids.
- **No LLM.** Templates alone are safe and stilted. The prototype keeps them as the fallback, so the LLM is an improvement, not a dependency.
- **Structured output only.** Used for rationales (`draft_rationale` returns a schema-checked object), but narration needs prose.

## Consequences

- Some correct model text is rejected (a spelled-out "two crews"). The selection evals in `tests/unit/agent/` measure how often each node falls back.
- Prompts, node models and slot formats are part of the replay contract: changing them invalidates the recordings in `data/fixtures/llm/`.
- Every LLM call goes through the gateway (ADR 0004), which writes an `llm_call` row with cost and outcome.
