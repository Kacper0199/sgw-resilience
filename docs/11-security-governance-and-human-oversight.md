# 11. Security, governance and human oversight

Audience: an assessor, a utility security reviewer or a compliance officer who asks: what stops the system, a buggy route or a manipulated input from acting on its own, and how would we know afterwards? Each control names the code and the test that pins it.

## Principles

- **People decide.** Every action that changes anything outside the platform needs a person's signature at a tier set by policy. The prototype has no write path to field equipment or control systems; T4 actions (direct control) have no tool at all.
- **The AI explains, never decides.** Models predict, deterministic code computes, the LLM writes explanations around values that code fills in.
- **Checks run twice.** Authority is checked by the policy engine and again by database triggers.
- **Everything leaves a trace.** Every state change is in a hash-chained, signed audit trail.

## Who can do what

Roles, functions and the permission sources are in [02. Roles and decision workflow](02-roles-and-decision-workflow.md). In short: eleven seeded people across ten functions; T2 decisions need one named function; T3 decisions need two people from two functions, neither the proposer; the auditor is read-only; the UI shows only what the API would allow (`GET /api/me/permissions`).

## Policy engine

OPA (Open Policy Agent) holds five policies in `policy/`: approval tiers, break-glass and co-sign, crew-plan envelopes, crew dispatch and LLM egress. Each policy is a deny-list: an empty list allows, anything undefined or malformed denies. Tier tables and governance values are generated into `policy/sgw/*/data.json` and tested table-driven (`policy/*_test.rego`).

- The server builds the policy input; the client and the model never supply a tier or a role.
- OPA accepts only decision queries with a bearer token; writes to its policies over the API are refused (`infra/opa/authz.rego`).
- **Fail closed.** When OPA cannot answer, the approval service refuses writes and the gateway refuses restricted egress (`tests/security/test_sec_63.py`).
- **Database triggers** refuse an execution token without the required signatures, an effect without a burned token, and the deletion of a break-glass row, even for a direct SQL insert by the runtime role (`db/migrations/4500_*`, `4501_*`, `4750_*`; `tests/security/test_sec_authority_writes.py`).

## Signing and sessions

- **Sign-in.** Passwords are hashed with Argon2id. The session cookie holds a random token and the database stores only its SHA-256. Every write carries a CSRF token derived from the session (`src/sgw/api/security.py`). Login and step-up attempts are rate-limited per client address and per user (`src/sgw/api/ratelimit.py`).
- **Step-up.** Emergency approval, co-sign and signing a kill-switch restore need the password re-entered within the last 5 minutes (`SteppedUp` in `src/sgw/api/deps.py`, `src/sgw/ops/control.py`).
- **Bound signatures.** A signature names the proposal version and action hash; a material change voids earlier signatures and the token (`tests/security/test_sec_47.py`). One person cannot sign twice, and two people from the same function do not make a T3 pair (`test_sec_16.py`, `test_sec_17.py`).

## Audit

Every state change appends to an insert-only, hash-chained `audit_event` table. The `audit-checkpoint` container signs the head with Ed25519 every 60 seconds and writes anchor files outside the database; an emergency approval is signed at once. `uv run sgw audit verify` names the first bad sequence, even after a superuser rewrote a row and recomputed every later hash (`tests/security/test_sec_52.py`). Mechanism: [02](02-roles-and-decision-workflow.md), "Audit trail".

## Human oversight of exceptions

- **Emergency approval** (break-glass) lets the Incident Commander alone approve a T3 action, with a written reason. The second function must co-sign within 24 hours; every use is flagged for the after-action review, and a late co-sign stays flagged (`src/sgw/approval/breakglass.py`).
- **Kill switch.** Levels K1 to K4 remove capabilities step by step: from K1 no approvals, tokens or effects; from K2 no agent runs; from K3 no ingestion and no new proposals (`src/sgw/ops/levels.py`, enforced again in `db/migrations/5000_ops_control.sql`). Raising a level is open to the incident commander, duty manager, water incident lead and executive roles; lowering it needs two people from `command` and `compliance` (`tests/security/test_sec_70.py`, `test_sec_73.py`).
- **Degraded modes.** When the LLM is down (`FAULT_LLM_DOWN=1` or the gateway breaker open) the platform enters mode M2: explanations fall back to templates filled with the same values, while clocks, dashboards and manual approvals keep working (`tests/security/test_sec_60.py`). A degraded mode also escalates T2 decisions to T3 (`policy/approval.rego`).

## What the LLM may and may not do

| May | May not |
| --- | --- |
| Explain a deadline, a forecast or a decision in words | Set, change or round a number: models see slot names, not values, and code fills `{E3.decide_by_p50}`-style slots (`src/sgw/agent/render/slots.py`) |
| Read platform data through read-only tools | Call any tool that writes: the copilot binds read-only tools only, and a request for any other tool is refused, counted and raised as an alert (`src/sgw/agent/copilot/tools.py`; `tests/security/test_sec_13.py`, `test_sec_14.py`) |
| Draft a situation report or a rationale | Approve, sign, dispatch or claim authority |
| Answer in the user's language | Put a link or markup in an answer |

The **verifier** (`src/sgw/agent/render/verify.py`) passes model text only when every slot is valid and every digit-bearing token outside a slot is an exact id from the run's evidence or the asset and document registry. It rejects number words, non-ASCII numerals, links, markup and sentences that claim approval. An invented id such as `PS-91` fails even if it looks right (`tests/security/test_sec_39.py`). On any failure the node uses its template with the same values. Ask AI in depth: [05](05-ask-ai-agent-system.md).

## Egress to the LLM provider

The LLM gateway (`services/llm_gateway/`) is the only service that reaches the provider and the only holder of the API key. Before every call, in every mode, it asks `policy/egress.rego`:

- **Data classes.** Each call declares the classes of its inputs (C0 to C4 and CX, ranked in `class_rank`). Route R1, the prototype route, allows C0 and C1 only; C3, C3-N, C4 and CX are allowed on no route (`tests/security/test_sec_30.py`).
- **Node allowlist.** Each calling node has a row in `src/sgw/agent/llm_nodes.yaml` with its models, class ceiling, beta headers and tool types; a call outside its row is denied. Attributes a caller asserts about itself are ignored (`tests/security/test_sec_m4_gateway_callers.py`).
- **Detectors.** Canary tokens planted in test documents and secret-shaped strings in the outbound body deny the call before any network request (`tests/security/test_sec_33.py`).
- **Budget.** Spend stops, a daily cap and a circuit breaker stop live calls; replay never touches the budget ([13. LLM gateway](13-llm-gateway.md), "Retries, breaker, budget").

The webhook worker is the only other service on the egress network; it refuses private, loopback and reserved targets (`src/sgw/integrations/urls.py`).

## Secrets

- `uv run sgw bootstrap` generates every credential into the git-ignored `var/`; none are committed and none have defaults ([ops/stack.md](ops/stack.md), "Boundaries").
- Each service gets only its own database login: the API the runtime role, the gateway an insert-only role on `llm_call`, the audit signer the private signing key (the API never mounts it).
- The Anthropic key is read only by the gateway, from the file named by `SGW_ENV_FILE`; without it the gateway runs in replay mode.
- A pre-commit hook scans staged files for secrets (`lefthook.yml`, `scripts/secret-scan.sh`).

## Prompt injection defences

Field notes, tickets, public alert text and retrieved documents are treated as untrusted data, never as instructions.

| Layer | Mechanism | Code and test |
| --- | --- | --- |
| Retrieved documents | Text is folded first (Unicode normalisation, zero-width characters removed, Cyrillic and Greek look-alikes mapped to Latin); sentences that address an automated reader, carry links or try to override instructions are withheld before any passage reaches a model | `src/sgw/agent/rag/guard.py`; `test_sec_03.py`, `test_sec_34.py` |
| Notes and tickets | The same folding plus role labels ("System:"), claims of approval ("counts as the second signature") and orders to the system; a flagged sentence is withheld from every prompt and quarantined; the run is marked tainted, which the approval card states | `src/sgw/agent/extract/guard.py`; `test_sec_01.py`, `test_sec_02.py`, `test_sec_06.py`, `test_sec_08.py` |
| Model output | The verifier (above) and the read-only tool set | `test_sec_13.py`, `test_sec_14.py`, `test_sec_39.py` |
| Ask AI questions | The wide gate checks by code, before its model step, for requests to change something and for instruction-like text; such questions get a helpful refusal with suggestions, and the question never steers anything but the choice of a read-only path | `src/sgw/agent/route/gate.py`, [05](05-ask-ai-agent-system.md) |

Detection is deterministic: a model's opinion never clears a flag. The red-team sets hold 7 dev cases and 23 held-out cases across notes, tickets, alerts, GIS attributes and user turns (`evals/dev/redteam.yaml`, `evals/heldout/redteam.yaml`). The held-out sets are hash-locked (`evals/MANIFEST.sha256`) but not yet scored by a release harness ([12](12-assumptions-limitations-and-improvements.md)); the security tests above run in the test suite.

## Data protection

- The repository holds no utility customer data and no personal data beyond the seeded synthetic identities, whose display names are role titles.
- Only synthetic or public content labelled C0 or C1 reaches the external model in the prototype. Above C1, a recording keeps no verbatim request ([13. LLM gateway](13-llm-gateway.md)).
- Recorded LLM answers are committed fixtures; live answers to unrecorded questions are cached only in the git-ignored `var/llm/live_cache/` ([dataset reference](04-data.md#dataset-reference)).
- Retention is an assumption: audit records are kept 7 years as SGW policy, above the legal floors found (2 to 10 years by record type).

Known gaps (the gateway trusts the declared class, sessions are not bound to per-user keys, a revoked session keeps an open stream) are listed in [12](12-assumptions-limitations-and-improvements.md).
