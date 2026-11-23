# ADR 0006: SSE for server-to-client streaming, REST for writes

Status: Accepted (2026-11-19)

## Context

The UI needs live updates: ledger events, clock state, agent run frames. Operators also write: approvals, signature withdrawals, kill switch, scenario clock commands. External systems need both a pull API and a push channel.

## Decision

- **Server to client: Server-Sent Events.** `/api/stream/ops` for ledger events and clock tiles, one stream per agent run (`/api/threads/{thread_id}/events`). Both resume with `Last-Event-ID` (ledger sequence or run frame sequence, with an epoch so a reset database forces a resync). The K4 wire format is fixed in `src/sgw/contracts/wire.py` with golden streams in `contracts/golden/streams/`.
- **Client to server: REST.** Every write is an idempotent, auditable request with CSRF protection and compare-and-set (`If-Match`) where state can race.
- **External systems:** the `/v1` API with scoped tokens, HMAC-signed webhooks, and an SSE subscription (built, mounted once the contract lists it).

## Alternatives considered

- **WebSocket.** Bidirectional, but approvals then need their own idempotency, CSRF and audit rules inside a socket protocol; proxies and corporate networks handle it less predictably than plain HTTP; reconnection and replay are custom work.
- **Polling.** Simple and robust, but clock tiles that move every minute and agent tokens would need short intervals and add load.

## Consequences

- Caddy must not buffer `/api` responses (`flush_interval -1`); the API sends `X-Accel-Buffering: no`.
- One uvicorn worker is assumed: a second process's broadcaster may lag, and a client reconnecting there gets a resync frame (see [limitations](../limitations.md)).
- The same streaming style as the provider APIs the agent layer already uses (Anthropic and OpenAI stream over SSE).
