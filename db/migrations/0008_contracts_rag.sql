-- K1 RAG tables (fastembed bge-small, 384 dimensions, O-14). LangGraph checkpointer tables live in schema `lg`
-- and are created by langgraph-checkpoint-postgres setup, not here.

CREATE TABLE document (
    doc_id         text PRIMARY KEY,
    title          text NOT NULL,
    source         text NOT NULL,
    licence        text NOT NULL,
    classification sgw_classification NOT NULL,
    trust          sgw_trust NOT NULL
);

CREATE TABLE doc_version (
    doc_version_id text PRIMARY KEY,
    doc_id         text NOT NULL REFERENCES document (doc_id),
    version        text NOT NULL,
    available_at   timestamptz NOT NULL,
    effective_from timestamptz NOT NULL,
    status         text NOT NULL CHECK (status IN ('current', 'superseded', 'draft')),
    content_hash   text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    UNIQUE (doc_id, version)
);

CREATE TABLE chunk (
    chunk_id       text PRIMARY KEY,
    doc_version_id text NOT NULL REFERENCES doc_version (doc_version_id),
    path           text NOT NULL,
    text           text NOT NULL,
    context_header text,
    tsv            tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(context_header, '') || ' ' || text)) STORED,
    embedding      vector(384),
    classification sgw_classification NOT NULL
);
CREATE INDEX chunk_tsv_idx ON chunk USING gin (tsv);
CREATE INDEX chunk_embedding_idx ON chunk USING hnsw (embedding vector_cosine_ops);
