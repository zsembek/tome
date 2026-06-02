-- Tome — knowledge base schema (Postgres). Idempotent. Everything in schema `tome`.
CREATE EXTENSION IF NOT EXISTS ltree;
-- pgvector is optional: if not installed, the semantic layer is disabled, BM25 still works.
DO $$ BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pgvector unavailable — semantic search will be disabled';
END $$;

-- The schema name is set by the code (init_schema): CREATE SCHEMA + SET search_path
-- run BEFORE this DDL, so all names here are without the schema prefix.

-- ── Multi-tenancy / settings ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspaces (
    id           BIGSERIAL PRIMARY KEY,
    slug         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    mode         TEXT NOT NULL DEFAULT 'enterprise',   -- enterprise | personal
    settings     JSONB NOT NULL DEFAULT '{}',          -- limits/thresholds/chunk sizes
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Folders (tree via ltree) ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS folders (
    id           BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    parent_id    BIGINT REFERENCES folders(id) ON DELETE CASCADE,
    path         LTREE NOT NULL,                       -- e.g. 'root.manuals.vendor_x'
    slug         TEXT NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workspace_id, path)
);
CREATE INDEX IF NOT EXISTS ix_folders_ws    ON folders (workspace_id);
CREATE INDEX IF NOT EXISTS ix_folders_path  ON folders USING GIST (path);
CREATE INDEX IF NOT EXISTS ix_folders_parent ON folders (parent_id);

-- ── Documents ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    workspace_id  BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    folder_id     BIGINT REFERENCES folders(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    tags          TEXT[] NOT NULL DEFAULT '{}',
    source_filename TEXT NOT NULL DEFAULT '',
    mime_type     TEXT NOT NULL DEFAULT '',
    source_object_key TEXT NOT NULL DEFAULT '',
    extractor     TEXT NOT NULL DEFAULT '',
    language      TEXT NOT NULL DEFAULT '',
    parts         INT NOT NULL DEFAULT 1,
    section_count INT NOT NULL DEFAULT 0,
    total_chars   INT NOT NULL DEFAULT 0,
    content_hash  TEXT NOT NULL DEFAULT '',
    pipeline_version TEXT NOT NULL DEFAULT '',
    faithfulness_score REAL,
    rev           INT NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'queued',       -- queued/processing/ready/error
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_documents_ws     ON documents (workspace_id);
CREATE INDEX IF NOT EXISTS ix_documents_folder ON documents (folder_id);

-- ── Document versions (edits/reimports, rollback, pending conflicts) ─────────
CREATE TABLE IF NOT EXISTS document_versions (
    id            BIGSERIAL PRIMARY KEY,
    document_id   BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no    INT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'applied',      -- applied | pending
    content_hash  TEXT NOT NULL DEFAULT '',
    pipeline_version TEXT NOT NULL DEFAULT '',
    model_id      TEXT NOT NULL DEFAULT '',
    faithfulness_score REAL,
    author        TEXT NOT NULL DEFAULT 'system',       -- user/agent/service
    change_kind   TEXT NOT NULL DEFAULT 'reimport',     -- reimport/section_edit/metadata/move
    snapshot_object_key TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_no)
);

-- ── Document parts (the original .partNN files, for get_document) ────────────
CREATE TABLE IF NOT EXISTS document_parts (
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    part_number  INT NOT NULL CHECK (part_number >= 1),
    content      TEXT NOT NULL,
    char_count   INT NOT NULL DEFAULT 0,
    PRIMARY KEY (document_id, part_number)
);

-- ── Sections (hierarchy by headings) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sections (
    id            BIGSERIAL PRIMARY KEY,
    document_id   BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_id     BIGINT REFERENCES sections(id) ON DELETE CASCADE,
    order_index   INT NOT NULL,
    level         INT NOT NULL CHECK (level BETWEEN 1 AND 6),
    heading       TEXT NOT NULL,
    breadcrumb    TEXT NOT NULL DEFAULT '',
    anchor_slug   TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL DEFAULT '',
    char_count    INT NOT NULL DEFAULT 0,
    language      TEXT NOT NULL DEFAULT 'simple',
    manually_edited BOOL NOT NULL DEFAULT FALSE,
    rev           INT NOT NULL DEFAULT 1,
    tsv           TSVECTOR,
    UNIQUE (document_id, order_index)
);
CREATE INDEX IF NOT EXISTS ix_sections_doc    ON sections (document_id, order_index);
CREATE INDEX IF NOT EXISTS ix_sections_parent ON sections (parent_id);
CREATE INDEX IF NOT EXISTS ix_sections_tsv    ON sections USING GIN (tsv);

-- ── Section revisions (full edit audit trail) ───────────────────────────────
CREATE TABLE IF NOT EXISTS section_revisions (
    id          BIGSERIAL PRIMARY KEY,
    section_id  BIGINT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    rev         INT NOT NULL,
    content     TEXT NOT NULL,
    author      TEXT NOT NULL DEFAULT 'system',
    source      TEXT NOT NULL DEFAULT 'edit',          -- edit/import/merge
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Retrieval chunks (separate from sections, for embeddings) ────────────────
CREATE TABLE IF NOT EXISTS retrieval_chunks (
    id            BIGSERIAL PRIMARY KEY,
    section_id    BIGINT NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    document_id   BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal       INT NOT NULL,
    text          TEXT NOT NULL,
    token_count   INT NOT NULL DEFAULT 0,
    embed_model_id TEXT NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_chunks_section ON retrieval_chunks (section_id);
CREATE INDEX IF NOT EXISTS ix_chunks_doc     ON retrieval_chunks (document_id);
-- The embedding column is added ONLY if pgvector is installed. Otherwise pure
-- BM25 is used (semantics disabled, the product remains functional).
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        EXECUTE 'ALTER TABLE retrieval_chunks ADD COLUMN IF NOT EXISTS embedding vector';
    END IF;
END $$;
-- The HNSW index is created dynamically after the first embedding (once the dimensionality is known).

-- ── Hierarchical Atlas (nodes generated from the DB) ─────────────────────────
CREATE TABLE IF NOT EXISTS atlas_nodes (
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    scope        TEXT NOT NULL,                         -- 'index' | 'folder:<id>'
    content_md   TEXT NOT NULL DEFAULT '',
    version      INT NOT NULL DEFAULT 1,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, scope)
);

-- ── Import jobs (observability + resumption) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id            BIGSERIAL PRIMARY KEY,
    workspace_id  BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    document_id   BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'queued',       -- queued/running/done/error
    stage         TEXT NOT NULL DEFAULT '',
    progress      REAL NOT NULL DEFAULT 0,
    tokens_in     BIGINT NOT NULL DEFAULT 0,
    tokens_out    BIGINT NOT NULL DEFAULT 0,
    cost_estimate REAL NOT NULL DEFAULT 0,
    faithfulness_score REAL,
    payload       JSONB NOT NULL DEFAULT '{}',
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON ingestion_jobs (status);

-- ── Assets (originals + images) ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assets (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    section_id   BIGINT REFERENCES sections(id) ON DELETE SET NULL,
    kind         TEXT NOT NULL,                         -- source | figure
    fig_class    TEXT,                                  -- schematic|photo|chart|logo|decor
    object_key   TEXT NOT NULL,
    mime         TEXT NOT NULL DEFAULT '',
    sha256       TEXT NOT NULL DEFAULT '',
    width        INT, height INT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_assets_doc ON assets (document_id);

-- ── Transactional outbox (DB ↔ MinIO consistency + webhooks) ─────────────────
CREATE TABLE IF NOT EXISTS outbox (
    id          BIGSERIAL PRIMARY KEY,
    aggregate   TEXT NOT NULL,
    op          TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_outbox_status ON outbox (status);

-- ── Access ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id           BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    key_hash     TEXT NOT NULL,
    scopes       TEXT[] NOT NULL DEFAULT '{read}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS webhooks (
    id           BIGSERIAL PRIMARY KEY,
    workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    url          TEXT NOT NULL,
    events       TEXT[] NOT NULL DEFAULT '{}',
    secret       TEXT NOT NULL DEFAULT ''
);

-- ── Users (identity) + sessions ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    workspace_id  BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,                          -- pbkdf2_hmac(sha256)
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'viewer',         -- admin | editor | viewer
    disabled      BOOL NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
-- case-insensitive uniqueness of email within a workspace (an expression →
-- only via an index; a table-constraint UNIQUE does not support expressions)
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_ws_email ON users (workspace_id, lower(email));
CREATE INDEX IF NOT EXISTS ix_users_ws ON users (workspace_id);

CREATE TABLE IF NOT EXISTS sessions (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,                    -- sha256(opaque token)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_sessions_token ON sessions (token_hash);
CREATE INDEX IF NOT EXISTS ix_sessions_user  ON sessions (user_id);

-- default workspace
INSERT INTO workspaces (slug, name, mode)
VALUES ('default', 'Default workspace', 'enterprise')
ON CONFLICT (slug) DO NOTHING;
