# Architecture decision records

Each record states the context, the decision, the alternatives considered and the consequences. Status values: Proposed, Accepted, Superseded.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-decision-clocks-as-the-core.md) | Decision clocks as the core object | Accepted |
| [0002](0002-authority-is-a-database-row.md) | Authority is a database row | Accepted |
| [0003](0003-llm-explains-never-decides.md) | The LLM explains, never decides: slots and a verifier | Accepted |
| [0004](0004-single-egress-gateway.md) | One gateway is the only egress to the LLM provider | Accepted |
| [0005](0005-postgres-only-light-stack.md) | Postgres as the only data store | Accepted |
| [0006](0006-sse-over-websocket.md) | SSE for server-to-client streaming, REST for writes | Accepted |

New records: copy the headings of an existing one, take the next number, and add a row here.
