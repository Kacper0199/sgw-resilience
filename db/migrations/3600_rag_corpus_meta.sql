-- WP-18 retrieval metadata beside the K1 RAG tables (document, doc_version, chunk stay as frozen in 0008).
-- In-force filtering uses effective_from and expires_at against the request's as_of, never doc_version.status.

CREATE TABLE rag_version_meta (
    doc_version_id  text PRIMARY KEY REFERENCES doc_version (doc_version_id) ON DELETE CASCADE,
    revision        text,
    change_no       integer CHECK (change_no IS NULL OR change_no > 0),
    citation_id     text NOT NULL,
    legacy_id       text,
    family          text NOT NULL,
    owner_function  text NOT NULL,
    expires_at      timestamptz,
    origin          text NOT NULL CHECK (origin IN ('core', 'extra', 'generated', 'federal')),
    page_count      integer NOT NULL CHECK (page_count > 0),
    rendered_sha256 text NOT NULL CHECK (rendered_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE rag_chunk_meta (
    chunk_id        text PRIMARY KEY REFERENCES chunk (chunk_id) ON DELETE CASCADE,
    ordinal         integer NOT NULL CHECK (ordinal >= 0),
    section         text NOT NULL,
    page_from       integer NOT NULL,
    page_to         integer NOT NULL,
    blocks          jsonb NOT NULL CHECK (jsonb_typeof(blocks) = 'array'),
    base_header     text NOT NULL,
    header_source   text NOT NULL CHECK (header_source IN ('llm', 'base')),
    content_sha256  text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$')
);

-- Exact-id lane: normalised spellings of document ids, legacy ids and citation ids.
CREATE TABLE rag_alias (
    alias_norm text NOT NULL,
    doc_id     text NOT NULL REFERENCES document (doc_id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('doc_id', 'legacy_id', 'citation_id')),
    PRIMARY KEY (alias_norm, doc_id)
);

CREATE INDEX doc_version_doc_effective_idx ON doc_version (doc_id, effective_from DESC);
CREATE INDEX chunk_doc_version_idx ON chunk (doc_version_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_app') THEN
        GRANT SELECT ON rag_version_meta, rag_chunk_meta, rag_alias TO sgw_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sgw_readonly') THEN
        GRANT SELECT ON rag_version_meta, rag_chunk_meta, rag_alias TO sgw_readonly;
    END IF;
END
$$;
