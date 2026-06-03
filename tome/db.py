"""Postgres access layer: pool, schema, repositories, atomic loading, search."""
from __future__ import annotations

import logging
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from tome.config import Config, get_config

log = logging.getLogger(__name__)
_HERE = Path(__file__).resolve().parent
SCHEMA_SQL = _HERE / "schema.sql"

# ── identity: passwords (pbkdf2) and roles ──────────────────────────────────
PBKDF_ITER = 600_000
ROLE_SCOPES = {
    "admin":  {"read", "write", "admin"},
    "editor": {"read", "write"},
    "viewer": {"read"},
}


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """pbkdf2_hmac(sha256, 600k) — OWASP-acceptable, no external dependencies."""
    import hashlib
    import secrets
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                            bytes.fromhex(salt), PBKDF_ITER).hex()
    return h, salt


def verify_password_hash(password: str, password_hash: str, salt: str) -> bool:
    import hmac
    calc, _ = hash_password(password, salt)
    return hmac.compare_digest(calc, password_hash)


def role_scopes(role: str) -> set[str]:
    return set(ROLE_SCOPES.get(role, set()))


def _configure(conn, schema: str):
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {schema}, public")
    conn.commit()


class DB:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or get_config()
        schema = self.cfg.db_schema
        self.pool = ConnectionPool(
            conninfo=self.cfg.postgres_dsn,
            min_size=1, max_size=8,
            kwargs={"row_factory": dict_row},
            configure=lambda c: _configure(c, schema),
            open=True,
        )

    def close(self):
        self.pool.close()

    # ── schema ──
    def init_schema(self):
        ddl = SCHEMA_SQL.read_text(encoding="utf-8")
        schema = self.cfg.db_schema
        import psycopg
        # The advisory lock serializes concurrent initialization from multiple
        # services (gateway/worker start in parallel). Without it, CREATE SCHEMA
        # IF NOT EXISTS races and fails with UniqueViolation (a known PG race).
        try:
            with self.pool.connection() as conn:
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_xact_lock(hashtext('tome_schema_init'))")
                    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                    cur.execute(f"SET search_path TO {schema}, public")
                    cur.execute(ddl)
            log.info("schema '%s' applied", schema)
        except psycopg.errors.UniqueViolation:
            # a parallel service already created the schema — this is normal
            log.info("schema '%s' already initialized (parallel start)", schema)

    def ensure_vector_index(self, dim: int):
        """Creates an HNSW index on retrieval_chunks.embedding once the
        dimension is known (after the first embeddings). Idempotent."""
        if not self.has_vector() or not dim:
            return
        with self.pool.connection() as conn, conn.cursor() as cur:
            try:
                cur.execute("SELECT 1 FROM pg_indexes WHERE indexname='ix_chunks_embedding'")
                if cur.fetchone():
                    return
                # fix the column dimension and build HNSW (cosine)
                cur.execute(f"ALTER TABLE retrieval_chunks ALTER COLUMN embedding TYPE vector({dim})")
                cur.execute("""CREATE INDEX IF NOT EXISTS ix_chunks_embedding
                               ON retrieval_chunks USING hnsw (embedding vector_cosine_ops)""")
                log.info("HNSW index created (dim=%d)", dim)
            except Exception as exc:
                log.warning("ensure_vector_index: %s", exc)

    def has_vector(self) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_type WHERE typname='vector'")
            return cur.fetchone() is not None

    def schema_ready(self) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT count(*)::int n FROM information_schema.tables
                           WHERE table_schema=%s AND table_name IN
                           ('workspaces','folders','documents','sections','retrieval_chunks')""",
                        (self.cfg.db_schema,))
            return cur.fetchone()["n"] == 5

    def default_workspace(self) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM workspaces WHERE slug='default'")
            row = cur.fetchone()
            return row["id"] if row else 1

    # ── folders (ltree tree) ──
    def ensure_folder_path(self, ws: int, path_str: str) -> int:
        """Creates a folder tree for the path 'A/B/C' cascadingly. Returns the leaf id."""
        from tome.pipeline.split import slugify
        parts = [p.strip() for p in path_str.split("/") if p.strip()]
        if not parts:
            return None
        parent_id, ltree_parts = None, []
        with self.pool.connection() as conn, conn.cursor() as cur:
            for name in parts:
                slug = slugify(name).replace("-", "_") or "f"
                ltree_parts.append(slug)
                lpath = ".".join(ltree_parts)
                cur.execute("SELECT id FROM folders WHERE workspace_id=%s AND path=%s::ltree",
                            (ws, lpath))
                row = cur.fetchone()
                if row:
                    parent_id = row["id"]
                    continue
                cur.execute("""INSERT INTO folders (workspace_id, parent_id, path, slug, name)
                               VALUES (%s,%s,%s::ltree,%s,%s) RETURNING id""",
                            (ws, parent_id, lpath, slug, name))
                parent_id = cur.fetchone()["id"]
        return parent_id

    def create_subfolder(self, ws: int, parent_id: int | None, name: str) -> int:
        """Create a single child folder under `parent_id` (or a root if None) by
        display name. Computes a unique ltree path. Returns the new folder id."""
        from tome.pipeline.split import slugify
        slug = slugify(name).replace("-", "_") or "f"
        with self.pool.connection() as conn, conn.cursor() as cur:
            if parent_id:
                cur.execute("SELECT path::text FROM folders WHERE id=%s AND workspace_id=%s",
                            (parent_id, ws))
                row = cur.fetchone()
                if not row:
                    raise ValueError("parent folder not found")
                base = f"{row['path']}.{slug}"
            else:
                base = slug
            lpath, i = base, 2
            while True:
                cur.execute("SELECT 1 FROM folders WHERE workspace_id=%s AND path=%s::ltree",
                            (ws, lpath))
                if not cur.fetchone():
                    break
                lpath = f"{base}{i}"; i += 1
            cur.execute("""INSERT INTO folders (workspace_id, parent_id, path, slug, name)
                           VALUES (%s,%s,%s::ltree,%s,%s) RETURNING id""",
                        (ws, parent_id, lpath, lpath.split(".")[-1], name))
            return cur.fetchone()["id"]

    def list_all_documents(self, ws: int) -> list[dict]:
        """All documents (id, title, folder_id) in a workspace — for the Atlas tree."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, title, folder_id, status FROM documents
                           WHERE workspace_id=%s ORDER BY title""", (ws,))
            return list(cur.fetchall())

    def folder_tree(self, ws: int) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT f.id, f.parent_id, f.path::text path, f.name, f.description,
                                  (SELECT count(*) FROM documents d WHERE d.folder_id=f.id) doc_count
                           FROM folders f WHERE workspace_id=%s ORDER BY f.path""", (ws,))
            return list(cur.fetchall())

    def folder_children(self, ws: int, parent_id: int | None) -> list[dict]:
        """Direct children of a folder (for lazy tree loading in the UI at scale)."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT f.id, f.parent_id, f.path::text path, f.name, f.description,
                                  (SELECT count(*) FROM documents d WHERE d.folder_id=f.id) doc_count,
                                  EXISTS(SELECT 1 FROM folders c WHERE c.parent_id=f.id) has_children
                           FROM folders f
                           WHERE workspace_id=%s AND parent_id IS NOT DISTINCT FROM %s
                           ORDER BY f.name""", (ws, parent_id))
            return list(cur.fetchall())

    def list_documents(self, folder_id: int, limit: int = 200, offset: int = 0) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, folder_id, title, summary, tags, parts, section_count,
                                  total_chars, language, status, faithfulness_score, updated_at
                           FROM documents WHERE folder_id=%s ORDER BY title
                           LIMIT %s OFFSET %s""", (folder_id, limit, offset))
            return list(cur.fetchall())

    def find_document(self, ws: int, folder_id: int | None, filename: str) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            if folder_id is None:
                cur.execute("""SELECT * FROM documents WHERE workspace_id=%s AND source_filename=%s
                               AND folder_id IS NULL ORDER BY id LIMIT 1""", (ws, filename))
            else:
                cur.execute("""SELECT * FROM documents WHERE workspace_id=%s AND source_filename=%s
                               AND folder_id=%s ORDER BY id LIMIT 1""", (ws, filename, folder_id))
            return cur.fetchone()

    def manual_edit_count(self, doc_id: int) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) n FROM sections WHERE document_id=%s AND manually_edited",
                        (doc_id,))
            return cur.fetchone()["n"]

    def create_pending_version(self, doc_id: int, *, snapshot_key: str, content_hash: str,
                               pipeline_version: str, faith: float | None) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(version_no),0)+1 v FROM document_versions WHERE document_id=%s",
                        (doc_id,))
            vno = cur.fetchone()["v"]
            cur.execute("""INSERT INTO document_versions (document_id, version_no, state,
                           content_hash, pipeline_version, faithfulness_score, change_kind,
                           snapshot_object_key) VALUES (%s,%s,'pending',%s,%s,%s,'reimport',%s)""",
                        (doc_id, vno, content_hash, pipeline_version, faith, snapshot_key))
            cur.execute("UPDATE documents SET status='conflict' WHERE id=%s", (doc_id,))
            return vno

    def get_pending_version(self, doc_id: int) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT * FROM document_versions WHERE document_id=%s AND state='pending'
                           ORDER BY version_no DESC LIMIT 1""", (doc_id,))
            return cur.fetchone()

    def discard_pending(self, doc_id: int):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM document_versions WHERE document_id=%s AND state='pending'",
                        (doc_id,))
            cur.execute("UPDATE documents SET status='ready' WHERE id=%s", (doc_id,))

    def get_document(self, doc_id: int) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM documents WHERE id=%s", (doc_id,))
            return cur.fetchone()

    def get_document_parts(self, doc_id: int, parts: list[int] | None) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            if parts:
                cur.execute("""SELECT part_number, content FROM document_parts
                               WHERE document_id=%s AND part_number=ANY(%s::int[])
                               ORDER BY part_number""", (doc_id, parts))
            else:
                cur.execute("""SELECT part_number, content FROM document_parts
                               WHERE document_id=%s ORDER BY part_number""", (doc_id,))
            return list(cur.fetchall())

    # ── sections ──
    def list_sections(self, doc_id: int, max_depth: int = 2,
                      parent_id: int | None = None) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            if parent_id is not None:
                cur.execute("""SELECT id, parent_id, order_index, level, heading, breadcrumb, char_count
                               FROM sections WHERE document_id=%s AND parent_id=%s
                               ORDER BY order_index""", (doc_id, parent_id))
            else:
                cur.execute("""SELECT id, parent_id, order_index, level, heading, breadcrumb, char_count
                               FROM sections WHERE document_id=%s AND level<=%s
                               ORDER BY order_index""", (doc_id, max_depth))
            return list(cur.fetchall())

    def get_section(self, section_id: int) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM sections WHERE id=%s", (section_id,))
            return cur.fetchone()

    def get_section_subtree(self, section_id: int) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""WITH RECURSIVE t AS (
                             SELECT * FROM sections WHERE id=%s
                             UNION ALL SELECT s.* FROM sections s JOIN t ON s.parent_id=t.id)
                           SELECT id, level, heading, content, order_index FROM t ORDER BY order_index""",
                        (section_id,))
            return list(cur.fetchall())

    def update_section(self, section_id: int, content: str, *, rev: int | None,
                       author: str = "user") -> dict:
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SELECT rev, language FROM sections WHERE id=%s FOR UPDATE", (section_id,))
                row = cur.fetchone()
                if not row:
                    raise ValueError("section not found")
                if rev is not None and rev != row["rev"]:
                    raise ConflictError(f"stale rev: have {row['rev']}, got {rev}")
                newrev = row["rev"] + 1
                cur.execute("""UPDATE sections SET content=%s, char_count=%s, rev=%s,
                               manually_edited=TRUE,
                               tsv=to_tsvector(%s::regconfig, %s) WHERE id=%s""",
                            (content, len(content), newrev,
                             self.cfg.fts_config, content, section_id))
                cur.execute("""INSERT INTO section_revisions (section_id, rev, content, author, source)
                               VALUES (%s,%s,%s,%s,'edit')""", (section_id, newrev, content, author))
            return {"section_id": section_id, "rev": newrev}

    # ── assets ──
    def insert_asset(self, *, document_id: int, kind: str, object_key: str,
                     fig_class: str | None = None, mime: str = "", sha: str = "",
                     section_id: int | None = None) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO assets (document_id, section_id, kind, fig_class,
                           object_key, mime, sha256) VALUES (%s,%s,%s,%s,%s,%s,%s)
                           RETURNING id""",
                        (document_id, section_id, kind, fig_class, object_key, mime, sha))
            return cur.fetchone()["id"]

    def get_asset_by_key(self, key: str) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM assets WHERE object_key=%s LIMIT 1", (key,))
            return cur.fetchone()

    def list_assets(self, document_id: int) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM assets WHERE document_id=%s ORDER BY id", (document_id,))
            return list(cur.fetchall())

    def enqueue_outbox(self, cur, aggregate: str, op: str, payload: dict):
        import json
        cur.execute("INSERT INTO outbox (aggregate, op, payload) VALUES (%s,%s,%s)",
                    (aggregate, op, json.dumps(payload)))

    def next_outbox(self, limit: int = 20) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT * FROM outbox WHERE status='pending'
                           ORDER BY id LIMIT %s FOR UPDATE SKIP LOCKED""", (limit,))
            return list(cur.fetchall())

    def mark_outbox(self, oid: int, status: str):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE outbox SET status=%s, attempts=attempts+1 WHERE id=%s",
                        (status, oid))

    def workspace_settings(self, ws: int) -> dict:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT settings FROM workspaces WHERE id=%s", (ws,))
            row = cur.fetchone()
            return (row["settings"] if row and isinstance(row["settings"], dict) else {})

    def emit_event(self, ws: int, event: str, body: dict):
        """Enqueues webhook delivery in the outbox for all workspace subscribers of the event."""
        import json
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT url, secret FROM webhooks WHERE workspace_id=%s AND %s = ANY(events)",
                        (ws, event))
            for r in cur.fetchall():
                cur.execute("INSERT INTO outbox (aggregate, op, payload) VALUES ('webhook','deliver',%s)",
                            (json.dumps({"url": r["url"], "event": event, "body": body,
                                         "secret": r.get("secret", "")}),))

    # ── api-keys / webhooks (admin) ──
    def has_any_api_key(self) -> bool:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM api_keys LIMIT 1")
            return cur.fetchone() is not None

    def create_api_key(self, ws: int, scopes: list[str]) -> tuple[int, str]:
        import secrets, hashlib
        token = "tome_" + secrets.token_urlsafe(32)
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO api_keys (workspace_id, key_hash, scopes)
                           VALUES (%s,%s,%s) RETURNING id""", (ws, h, scopes))
            kid = cur.fetchone()["id"]
        return kid, token  # plaintext is returned ONLY ONCE

    def list_api_keys(self, ws: int) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, scopes, created_at, last_used_at,
                           ('…'||right(key_hash,6)) AS hint
                           FROM api_keys WHERE workspace_id=%s ORDER BY id""", (ws,))
            return list(cur.fetchall())

    def delete_api_key(self, ws: int, key_id: int):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM api_keys WHERE id=%s AND workspace_id=%s", (key_id, ws))

    def verify_api_key(self, token: str) -> dict | None:
        import hashlib
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, workspace_id, scopes FROM api_keys WHERE key_hash=%s", (h,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE api_keys SET last_used_at=NOW() WHERE id=%s", (row["id"],))
            return row

    def create_webhook(self, ws: int, url: str, events: list[str], secret: str = "") -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO webhooks (workspace_id, url, events, secret)
                           VALUES (%s,%s,%s,%s) RETURNING id""", (ws, url, events, secret))
            return cur.fetchone()["id"]

    def list_webhooks(self, ws: int) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, url, events FROM webhooks WHERE workspace_id=%s ORDER BY id", (ws,))
            return list(cur.fetchall())

    def delete_webhook(self, ws: int, wid: int):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM webhooks WHERE id=%s AND workspace_id=%s", (wid, ws))

    # ── users / sessions (identity) ──
    def count_users(self) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*)::int n FROM users")
            return cur.fetchone()["n"]

    def create_user(self, ws: int, email: str, password: str, role: str = "viewer") -> dict:
        if role not in ROLE_SCOPES:
            raise ValueError(f"unknown role: {role}")
        ph, salt = hash_password(password)
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO users (workspace_id, email, password_hash, salt, role)
                           VALUES (%s,%s,%s,%s,%s) RETURNING id, email, role, disabled, created_at""",
                        (ws, email.strip(), ph, salt, role))
            return cur.fetchone()

    def get_user(self, uid: int) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, workspace_id, email, role, disabled, created_at, last_login_at
                           FROM users WHERE id=%s""", (uid,))
            return cur.fetchone()

    def get_user_by_email(self, ws: int, email: str) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, workspace_id, email, password_hash, salt, role, disabled
                           FROM users WHERE workspace_id=%s AND lower(email)=lower(%s)""",
                        (ws, email.strip()))
            return cur.fetchone()

    def list_users(self, ws: int) -> list[dict]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, email, role, disabled, created_at, last_login_at
                           FROM users WHERE workspace_id=%s ORDER BY id""", (ws,))
            return list(cur.fetchall())

    def update_user(self, ws: int, uid: int, role: str | None = None,
                    password: str | None = None, disabled: bool | None = None) -> None:
        sets, params = [], []
        if role is not None:
            if role not in ROLE_SCOPES:
                raise ValueError(f"unknown role: {role}")
            sets.append("role=%s"); params.append(role)
        if password is not None:
            ph, salt = hash_password(password)
            sets.append("password_hash=%s"); params.append(ph)
            sets.append("salt=%s"); params.append(salt)
        if disabled is not None:
            sets.append("disabled=%s"); params.append(disabled)
        if not sets:
            return
        params += [uid, ws]
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=%s AND workspace_id=%s", params)
            # password change/disable → invalidate the user's active sessions
            if password is not None or disabled:
                cur.execute("DELETE FROM sessions WHERE user_id=%s", (uid,))

    def delete_user(self, ws: int, uid: int) -> None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id=%s AND workspace_id=%s", (uid, ws))

    def verify_login(self, ws: int, email: str, password: str) -> dict | None:
        """Verifies email+password. Constant-time, with a dummy hash when the user is absent
        (protects against timing-based user enumeration). Returns a safe profile."""
        row = self.get_user_by_email(ws, email)
        if not row:
            hash_password(password, "00" * 16)  # equalize timing
            return None
        if row["disabled"]:
            return None
        if not verify_password_hash(password, row["password_hash"], row["salt"]):
            return None
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE users SET last_login_at=NOW() WHERE id=%s", (row["id"],))
        return {"id": row["id"], "workspace_id": row["workspace_id"],
                "email": row["email"], "role": row["role"]}

    def create_session(self, user_id: int, ttl_hours: int = 168) -> str:
        import secrets, hashlib
        token = "toms_" + secrets.token_urlsafe(32)
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO sessions (user_id, token_hash, expires_at)
                           VALUES (%s,%s, NOW() + (%s || ' hours')::interval)""",
                        (user_id, h, str(int(ttl_hours))))
        return token

    def verify_session(self, token: str) -> dict | None:
        """Returns {user_id, workspace_id, email, role, scopes} or None."""
        if not token:
            return None
        import hashlib
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT s.id sid, s.user_id, s.expires_at, u.workspace_id,
                                  u.email, u.role, u.disabled
                           FROM sessions s JOIN users u ON u.id=s.user_id
                           WHERE s.token_hash=%s AND s.expires_at > NOW()""", (h,))
            row = cur.fetchone()
            if not row or row["disabled"]:
                return None
            cur.execute("UPDATE sessions SET last_seen_at=NOW() WHERE id=%s", (row["sid"],))
        return {"user_id": row["user_id"], "workspace_id": row["workspace_id"],
                "email": row["email"], "role": row["role"], "scopes": role_scopes(row["role"])}

    def delete_session(self, token: str) -> None:
        if not token:
            return
        import hashlib
        h = hashlib.sha256(token.encode()).hexdigest()
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash=%s", (h,))

    def purge_expired_sessions(self) -> int:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE expires_at <= NOW()")
            return cur.rowcount or 0

    # ── atlas ──
    def get_atlas(self, ws: int, scope: str = "index") -> str:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT content_md FROM atlas_nodes WHERE workspace_id=%s AND scope=%s",
                        (ws, scope))
            row = cur.fetchone()
            return row["content_md"] if row else ""

    def upsert_atlas(self, ws: int, scope: str, content_md: str):
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO atlas_nodes (workspace_id, scope, content_md)
                           VALUES (%s,%s,%s)
                           ON CONFLICT (workspace_id, scope) DO UPDATE
                           SET content_md=EXCLUDED.content_md, version=atlas_nodes.version+1,
                               updated_at=NOW()""", (ws, scope, content_md))

    # ── jobs ──
    def create_job(self, ws: int, payload: dict) -> int:
        import json
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO ingestion_jobs (workspace_id, payload) VALUES (%s,%s)
                           RETURNING id""", (ws, json.dumps(payload)))
            return cur.fetchone()["id"]

    def update_job(self, job_id: int, **fields):
        if not fields:
            return
        from psycopg.types.json import Json
        cols = ", ".join(f"{k}=%s" for k in fields)
        vals = [Json(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(f"UPDATE ingestion_jobs SET {cols}, updated_at=NOW() WHERE id=%s",
                        (*vals, job_id))

    def get_job(self, job_id: int) -> dict | None:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM ingestion_jobs WHERE id=%s", (job_id,))
            return cur.fetchone()

    def document_extract_confidence(self, doc_id: int) -> float | None:
        """OCR/extract confidence reported by the latest completed ingest job."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT payload->>'extract_confidence' v FROM ingestion_jobs
                           WHERE document_id=%s ORDER BY id DESC LIMIT 1""", (doc_id,))
            row = cur.fetchone()
        try:
            return float(row["v"]) if row and row["v"] not in (None, "", "null") else None
        except (TypeError, ValueError):
            return None

    def next_queued_job(self) -> dict | None:
        with self.pool.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("""SELECT * FROM ingestion_jobs WHERE status='queued'
                               ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED""")
                row = cur.fetchone()
                if row:
                    cur.execute("UPDATE ingestion_jobs SET status='running', updated_at=NOW() WHERE id=%s",
                                (row["id"],))
                return row

    def requeue_stale_jobs(self, minutes: int = 30) -> int:
        """Jobs in 'running' for longer than N minutes (worker crashed/hung) → back to 'queued'.
        Without this, dead imports hang forever. Returns the number requeued."""
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE ingestion_jobs
                           SET status='queued', stage='', updated_at=NOW()
                           WHERE status='running'
                             AND updated_at < NOW() - (%s || ' minutes')::interval
                           RETURNING id""", (str(minutes),))
            return len(cur.fetchall())


class ConflictError(Exception):
    pass


def _regconfig(language: str) -> str:
    return {"ru": "russian", "en": "english", "de": "german", "fr": "french",
            "es": "spanish", "it": "italian"}.get((language or "")[:2], "simple")
