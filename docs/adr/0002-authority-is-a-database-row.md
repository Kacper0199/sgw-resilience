# ADR 0002: Authority is a database row

Status: Accepted (2026-11-19)

## Context

Decision support with an LLM in the loop raises one question from every utility reviewer: what stops the system, or a prompt injection, from acting on its own? An answer that lives only in application code ("the service checks the role") is weak: one missed check in one route undoes it, and an auditor cannot read it.

## Decision

Approval authority is enforced twice, and the second check is in Postgres:

1. **Policy first.** OPA (`policy/approval.rego`) classifies the action and returns the tier and the required functions. The client never supplies the tier. The tier table is generated into `policy/sgw/tiers/data.json` and tested table-driven.
2. **Triggers second.** On insert, database triggers re-check the same rules (`db/migrations/0005_contracts_analysis_actions.sql`, `4500_approval_execution_token_binding.sql`, `4501_approval_effect_needs_burned_token.sql`, `4750_breakglass_authority.sql`):
   - an approval must come from a function the tier requires, from a person who is not the proposer;
   - an execution token can exist only for an approved proposal whose current version carries every required function from distinct non-proposers, or a break-glass row bound to the same version and hash;
   - the token is single-use (it can only gain `burned_at`, once) and bound to `proposal_version` and `action_hash`;
   - an effect row needs a burned token;
   - break-glass rows are never deleted and can only gain a co-signature from a second function.
3. **Compare-and-set.** Approvals send `If-Match` with the proposal version; a material revision voids earlier signatures.
4. **Kill switch.** The control-plane migration (`5000_ops_control.sql`) refuses approvals, tokens and effects while a kill level is set, and only a two-function restore lowers it.

SQLSTATE codes map to HTTP: 42501 to 403, 09000 (stale version or hash) to 412.

## Alternatives considered

- **Application checks only.** Faster to write; fails open when one route forgets a check.
- **Policy engine only.** OPA alone still trusts the caller to ask it. The triggers make the database refuse even a direct SQL insert by the runtime role.
- **Signatures with per-user keys.** Stronger non-repudiation, but key management for every approver is out of scope for a prototype; the hash-chained audit trail with signed checkpoints covers tamper evidence.

## Consequences

- Every rule exists in two languages (Rego and PL/pgSQL). Tests pin both: `policy/approval_test.rego` and the DB tests in `tests/unit/approval/`.
- There is no write path to operational technology. "Execute" records an effect row; T4 actions have no tool at all.
- The runtime role cannot rewrite the ledger or the audit tables (insert-only grants), so an API compromise cannot erase its own trail.
