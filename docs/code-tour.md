# Code tour: twelve files on the golden path

Audience: a reviewer with an hour who wants to see where the important behaviour lives. Read in this order; each stop names the file, what it does and why it is built that way, and the test that pins it. Architecture context: [architecture.md](architecture.md).

## 1. Decision clocks

[`src/sgw/models/clocks/service.py`](../src/sgw/models/clocks/service.py), with [`waterfall.py`](../src/sgw/models/clocks/waterfall.py), [`critical_path.py`](../src/sgw/models/clocks/critical_path.py) and the contract [`src/sgw/contracts/clocks.py`](../src/sgw/contracts/clocks.py)

- Turns model outputs into decision cases: consequence time minus action lead time, per ensemble member, then P10/P50/P90, each term tagged with its model or rule id.
- A backward pass over the prerequisite graph gives the effective decide-by, because a fuel truck that arrives too late makes an on-time generator order useless.
- "Wait for the next advisory" is offered only when that advisory lands before the earliest P10 effective decide-by; pinned by `tests/unit/models/clocks/test_clocks_properties.py` and the golden vectors in `test_clocks_golden.py`.

## 2. Water continuity twin

[`src/sgw/models/water/twin.py`](../src/sgw/models/water/twin.py)

- Simulates a zone tank draining, minute by minute, until the lowest service connection falls below the state pressure floor; that time is PS-17's consequence time.
- A reduced model instead of full EPANET at run time: it is fast enough for every ensemble member, and `uv run sgw water validate` checks it against a WNTR (EPANET 2.2) grid computed on the host.
- The floor is checked at the hospital connection, which sits lower in pressure than the station sensor, so the clock is earlier than a station-level drain; see `tests/unit/models/water/test_validation_and_floors.py`.

## 3. Approvals and the database triggers

[`src/sgw/approval/service.py`](../src/sgw/approval/service.py) with [`db/migrations/4500_approval_execution_token_binding.sql`](../db/migrations/4500_approval_execution_token_binding.sql) and [`4750_breakglass_authority.sql`](../db/migrations/4750_breakglass_authority.sql)

- Creates proposals with the tier from policy, records approvals with compare-and-set on the version, and issues a single-use execution token bound to `proposal_version` and `action_hash`.
- The same rules are enforced again by triggers, so even a direct SQL insert by the runtime role cannot create a token without two functions' signatures or a break-glass row ([ADR 0002](adr/0002-authority-is-a-database-row.md)).
- Tests: `tests/unit/approval/test_service.py`, `tests/security/test_sec_16.py`, `test_sec_17.py`, `test_sec_47.py`.

## 4. Audit chain

[`src/sgw/approval/audit.py`](../src/sgw/approval/audit.py)

- Appends hash-chained records (RFC 8785 canonical JSON, SHA-256), signs the head with Ed25519 at checkpoints and writes anchor files outside the database.
- Anchors carry the row hashes of each segment, so a rewrite that recomputes every later hash is still pinpointed to the first edited sequence.
- `uv run sgw audit verify` exits 1 with the first bad sequence; tamper cases in `tests/security/test_sec_52.py` (rewrite, deletion, reorder, re-signing).

## 5. LLM egress gate

[`services/llm_gateway/egress.py`](../services/llm_gateway/egress.py) with [`policy/egress.rego`](../policy/egress.rego)

- Asks the egress policy before every model call, in every mode, with the declared data classes, the node's allowlist row and detector counts for canaries and secret shapes.
- One process, one network route and one key holder, so data-class rules are enforced in one place ([ADR 0004](adr/0004-single-egress-gateway.md)); an unreachable OPA denies.
- A Python twin of the policy runs where OPA is absent; a parity test runs both over one case table. Tests: `tests/security/test_sec_30.py`, `test_sec_33.py`.

## 6. Output verifier

[`src/sgw/agent/render/verify.py`](../src/sgw/agent/render/verify.py)

- Accepts model text only if every value is a slot filled by code and every other digit-bearing token is an exact id from the run's evidence or the asset and document registry.
- Shape-based id matching would let an invented `PS-91` through; exact matching does not ([ADR 0003](adr/0003-llm-explains-never-decides.md)).
- On failure the node falls back to a template with the same slot values. Tests: `tests/unit/agent/test_render.py`, `tests/security/test_sec_39.py`.

## 7. Retrieval guard

[`src/sgw/agent/rag/guard.py`](../src/sgw/agent/rag/guard.py)

- Withholds lines of retrieved procedures that address an automated reader, carry links or try to override instructions, before any passage reaches a model.
- Field records (ICS forms, vendor tickets, OCR'd notes) can carry an injected instruction in house style, so the guard folds homoglyphs and checks paragraphs and table rows as a reader sees them, withholding only the flagged part.
- The index keeps the original text, so the record is still found by search. Tests: `tests/unit/agent/rag/test_guard_attacks.py`.

## 8. Kill switch and degraded modes

[`src/sgw/ops/control.py`](../src/sgw/ops/control.py) with [`db/migrations/5000_ops_control.sql`](../db/migrations/5000_ops_control.sql)

- Sets kill levels K0-K4 and degraded modes M0-M4 from signals (`FAULT_*` flags, gateway and OPA probes); every change is audited, published to the ledger and checkpointed at once.
- The database refuses approvals, tokens and effects while a kill level is set, and only a restore signed by `command` and `compliance` lowers it; an unreadable control row reads as K1.
- `uv run sgw ops rules` prints the ladder. Tests: `tests/unit/ops/test_control_db.py`, `tests/security/test_sec_60.py`, `test_sec_70.py`.

## 9. Agent runs router

[`src/sgw/api/routers/runs.py`](../src/sgw/api/routers/runs.py)

- Starts a graph run (`assess`, `water_continuity`, `etr`, `sitrep`, `after_action`, `copilot` for Ask AI) in the API process and streams its frames as SSE, resumable with `Last-Event-ID`.
- Identity and function come from the session, never from the request body; forged input keys are dropped by the graph and audited; threads belong to their creator (others get 404).
- A run paused for approval lives in the LangGraph Postgres checkpointer, and only the approval store, not the resume call, decides whether it executes. Tests: `tests/unit/agent/test_runs_router.py`.

## 10. Integrations: webhooks

[`src/sgw/integrations/delivery.py`](../src/sgw/integrations/delivery.py) with [`signing.py`](../src/sgw/integrations/signing.py)

- Claims due deliveries with `FOR UPDATE SKIP LOCKED` and a lease, signs each attempt with HMAC-SHA256 and a fresh timestamp, retries with backoff, and dead-letters after the last attempt.
- At-least-once with a deterministic delivery id, so receivers de-duplicate; two secrets sign during a rotation window so receivers switch at their own pace.
- A target that now resolves to a private address counts as a failed attempt with no request sent. Tests: `tests/unit/integrations/`; example receiver in [`examples/webhook-consumer/`](../examples/webhook-consumer/).

## 11. Ask AI gate and team

[`src/sgw/agent/route/gate.py`](../src/sgw/agent/route/gate.py) with [`src/sgw/agent/copilot/graph.py`](../src/sgw/agent/copilot/graph.py), [`plan.py`](../src/sgw/agent/copilot/plan.py), [`workers.py`](../src/sgw/agent/copilot/workers.py), [`synthesis.py`](../src/sgw/agent/copilot/synthesis.py) and [`guide.py`](../src/sgw/agent/copilot/guide.py)

- The gate gives every question the first router sent out of scope a second look, code first: write requests and instruction-like text are declined helpfully, photo and "where can I find" questions go to the guide, the rest to a small model that also returns "did you mean" readings.
- The team engine plans one to three read-only workers, runs them in parallel, merges their findings in a fixed order (so the replay hash does not depend on timing) and writes one checked answer; the guide answers navigation, definitions and photo requests with links built by code.
- Every model step has a code fallback, and the graph has no approval step: Ask cannot change anything. Tests: `tests/unit/agent/` (copilot and route suites); the question bank in [`evals/ask_bank/`](../evals/ask_bank/README.md).

## 12. Scenario packs

[`src/sgw/scenarios/packs.py`](../src/sgw/scenarios/packs.py) with [`reads.py`](../src/sgw/scenarios/reads.py), [`src/sgw/api/routers/demo.py`](../src/sgw/api/routers/demo.py) and the pack [`data/scenarios/ian-2022/`](../data/scenarios/ian-2022/)

- Loads a scripted exercise from YAML (period, moments, real best track, scripted outage curve, facilities, crew roster, timed decisions) and answers the page reads from it when the scenario clock names the pack.
- `POST /api/demo/scenario` starts a pack from the quiet Helene template and switches the clock before the API follows the new database, so every client resyncs once, into the exercise; going back loads the saved Helene moment, so the Helene demo stays byte-identical.
- Pages without a model for the pack show one plain "Not modelled for this scenario" state instead of Helene data. Tests: `tests/unit/api/test_ian_pack.py`, `tests/unit/api/test_scenario_load.py`, `web/e2e/scenario-ian.spec.ts` (load Ian, act as several roles, back to Helene).

