# ADR 0004: One gateway is the only egress to the LLM provider

Status: Accepted (2026-11-19)

## Context

A utility will ask three things about any external model API: which data leaves, who holds the key, and what happens when the provider is down or the budget is spent. If every service calls the provider directly, each answer has to be checked in every service.

## Decision

`services/llm_gateway` is the only process that talks to the Anthropic Messages API and the only holder of the key:

- It is the only container that reaches the provider. api, worker, OPA and Postgres sit on an internal network with no route out. The `egress` network has one other member, the webhook worker, which delivers signed webhooks and refuses private, loopback and reserved targets (`src/sgw/integrations/urls.py`).
- Clients call it exactly like the provider API (`base_url` set to the gateway, any placeholder key, client retries off).
- Before every call, in every mode, it asks the egress policy (`policy/egress.rego`): data classes allowed per route (R1 allows C0 and C1 only), the calling node's allowlist row (model, class ceiling, betas, tool types), and detector counts for canaries and secret shapes. It fails closed when OPA is unreachable.
- It records and replays calls (K11 format, `data/fixtures/llm/`). Replay mode needs no key, so a fresh clone and CI run every agent graph offline.
- It enforces budget stops, retries with jitter, a circuit breaker, and writes one `llm_call` row per decision through a dedicated insert-only database role.

Details: [docs/gateway.md](../gateway.md).

## Alternatives considered

- **Provider SDK in each service.** Simplest code, no single place to enforce data classes, and the key in several containers.
- **A third-party LLM proxy.** Covers keys and budgets, but not the project's data-class policy, the replay format or the `llm_call` audit rows without custom plugins.

## Consequences

- One more service to run and test (gateway unit tests, SEC-30 and SEC-33 security tests).
- A request whose hash is not in the recordings fails in replay mode. The node then uses its template, which the demo path accepts.
- Data classes are declared by the caller. A mislabelled payload is not caught by content inspection beyond the canary and secret detectors (see [limitations](../limitations.md)).
