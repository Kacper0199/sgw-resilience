# ADR 0005: Postgres as the only data store

Status: Accepted (2026-11-19)

## Context

The platform needs an event log, time series, geometry, vector search for procedures, a job queue, agent checkpoints and an append-only audit trail. A common answer is one product per need (Kafka, InfluxDB, a vector database, Redis, a workflow engine). The prototype must run on one laptop with 8 GB for Docker, and a reviewer must be able to start it with one command on macOS, Linux or Windows.

## Decision

One Postgres 18 instance (`timescale/timescaledb-ha`, digest-pinned) holds everything, with eight extensions: TimescaleDB (observation hypertable), PostGIS, H3 and pgRouting (geometry, hex cells, routing), pgvector and pgvectorscale (procedure embeddings), btree_gist (exclusion constraints) and pgcrypto.

| Need | Postgres feature |
| --- | --- |
| Event log | `event` ledger with gapless sequence, written by one relay from a transactional outbox |
| Live push | `LISTEN/NOTIFY` on ledger head |
| Job queue | `job` table claimed with `FOR UPDATE SKIP LOCKED` and a lease |
| Agent state | LangGraph Postgres checkpointer |
| Retrieval | hybrid search: dense vectors plus full-text, fused with reciprocal rank |
| Audit | insert-only hash chain with triggers; signed checkpoints anchored to files |

## Alternatives considered

- **Kafka for the ledger.** Strong for many producers and consumers at scale; adds a broker and a schema registry to every laptop run, and still needs a database for state.
- **Dedicated vector database.** About 700 chunks today; pgvector is exact at that size and keeps the in-force filter in the same SQL query.
- **Redis for queues and pub/sub.** A second store to secure and back up for a load Postgres handles.

## Consequences

- The core stack is nine small containers and fits the memory limits listed in [docs/ops/stack.md](../ops/stack.md).
- Postgres is a single point of failure in the prototype. The pilot architecture in [docs/tradeoffs.md](../tradeoffs.md) adds managed high availability and names the point at which a log broker becomes worth it.
- Transactional outbox plus one relay keeps writes and their events in one transaction, so there is no dual-write problem.
