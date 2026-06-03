"""Agent memory — Markdown-native long-term memory for agents.

Memory is ordinary **Markdown** stored in the `agent_memory` table (kept separate
from the document KB so it never pollutes the folder tree / Atlas). It is
retrievable by the same BM25 (+ optional vector) machinery as documents.

Tiers (agentmemory-style consolidation):
  • working    — raw, short-lived observations (auto-captured)
  • episodic   — per-session summary (LLM roll-up, or raw fallback)
  • semantic   — durable facts/decisions promoted from episodes
  • procedural — durable how-tos / patterns

Hygiene: secrets are redacted before storage (WI-3.4), recall reinforces
importance, and `decay_and_gc` lets old low-value memories fade. Visibility is
scoped per agent: `shared` memories are workspace-wide, `agent` memories are
private to the writing agent_id.
"""
from __future__ import annotations

import hashlib
import logging

from tome.config import get_config
from tome.db import DB
from tome.redact import redact
from tome.store import _vec

log = logging.getLogger(__name__)

TIERS = ("working", "episodic", "semantic", "procedural")
DURABLE_TIERS = ("semantic", "procedural")
_RECALL_BOOST = 0.1
_IMPORTANCE_CAP = 10.0


def _default_scope() -> str:
    return "agent" if get_config().memory_scope == "isolated" else "shared"


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _has_embedding_col(db: DB) -> bool:
    return db.has_vector()


def _visibility(agent_id: str) -> tuple[str, list]:
    """SQL fragment + params restricting rows visible to `agent_id`."""
    return "(scope='shared' OR agent_id=%s)", [agent_id]


# ─────────────────────────── write ───────────────────────────
def remember(db: DB, *, ws: int, agent_id: str, content: str, title: str = "",
             tier: str = "semantic", scope: str | None = None, mkey: str = "",
             session_id: str = "", importance: float = 1.0,
             embedding: list[float] | None = None, redact_secrets: bool | None = None) -> dict:
    """Store a Markdown memory. If `mkey` is set, any earlier active memory with
    the same (agent_id, mkey) is superseded (contradiction resolution)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    scope = scope or _default_scope()
    do_redact = get_config().memory_redact if redact_secrets is None else redact_secrets
    if do_redact:
        content = redact(content)
        title = redact(title)
    chash = _hash(content)
    rc = get_config().fts_config
    use_emb = embedding is not None and _has_embedding_col(db)
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            if use_emb:
                cur.execute(
                    """INSERT INTO agent_memory
                       (workspace_id, agent_id, scope, tier, session_id, mkey, title,
                        content, content_hash, importance, embedding, tsv)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               to_tsvector(%s::regconfig, %s))
                       RETURNING *""",
                    (ws, agent_id, scope, tier, session_id, mkey, title, content, chash,
                     importance, _vec(embedding), rc, f"{title} {content}"))
            else:
                cur.execute(
                    """INSERT INTO agent_memory
                       (workspace_id, agent_id, scope, tier, session_id, mkey, title,
                        content, content_hash, importance, tsv)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                               to_tsvector(%s::regconfig, %s))
                       RETURNING *""",
                    (ws, agent_id, scope, tier, session_id, mkey, title, content, chash,
                     importance, rc, f"{title} {content}"))
            row = cur.fetchone()
            if mkey:
                cur.execute(
                    """UPDATE agent_memory SET superseded_by=%s, updated_at=NOW()
                       WHERE workspace_id=%s AND agent_id=%s AND mkey=%s
                         AND id<>%s AND superseded_by IS NULL
                       RETURNING id, tier, content_hash""",
                    (row["id"], ws, agent_id, mkey, row["id"]))
                for old in cur.fetchall():
                    _audit(cur, ws, old["id"], agent_id, old["tier"], "supersede",
                           author="agent", reason=f"superseded by {row['id']}",
                           content_hash=old["content_hash"])
    return dict(row)


def observe(db: DB, *, ws: int, agent_id: str, content: str, session_id: str = "",
            scope: str | None = None, redact_secrets: bool | None = None) -> dict:
    """Append a raw working-tier observation. De-duplicates identical content
    within the same (agent_id, session_id) so auto-capture hooks are idempotent."""
    scope = scope or _default_scope()
    do_redact = get_config().memory_redact if redact_secrets is None else redact_secrets
    stored = redact(content) if do_redact else content
    chash = _hash(stored)
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT * FROM agent_memory
               WHERE workspace_id=%s AND agent_id=%s AND session_id=%s AND tier='working'
                 AND content_hash=%s AND superseded_by IS NULL LIMIT 1""",
            (ws, agent_id, session_id, chash))
        existing = cur.fetchone()
    if existing:
        return dict(existing)
    return remember(db, ws=ws, agent_id=agent_id, content=content, tier="working",
                    scope=scope, session_id=session_id, importance=0.5,
                    redact_secrets=do_redact)


def forget(db: DB, *, ws: int, mem_id: int, author: str = "agent", reason: str = "") -> bool:
    """Delete a memory and record an audit entry. Returns True if a row was removed."""
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT id, agent_id, tier, content_hash FROM agent_memory "
                        "WHERE id=%s AND workspace_id=%s", (mem_id, ws))
            row = cur.fetchone()
            if not row:
                return False
            _audit(cur, ws, row["id"], row["agent_id"], row["tier"], "forget",
                   author=author, reason=reason, content_hash=row["content_hash"])
            cur.execute("DELETE FROM agent_memory WHERE id=%s AND workspace_id=%s", (mem_id, ws))
    return True


# ─────────────────────────── read ───────────────────────────
def get_memory(db: DB, *, ws: int, mem_id: int) -> dict | None:
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM agent_memory WHERE id=%s AND workspace_id=%s", (mem_id, ws))
        row = cur.fetchone()
    return dict(row) if row else None


def list_memory(db: DB, *, ws: int, agent_id: str, tier: str | None = None,
                scope: str | None = None, limit: int = 100, offset: int = 0,
                include_superseded: bool = False) -> list[dict]:
    vis, params = _visibility(agent_id)
    sql = [f"SELECT id, agent_id, scope, tier, session_id, mkey, title, content, "
           f"importance, access_count, created_at, last_accessed_at "
           f"FROM agent_memory WHERE workspace_id=%s AND {vis}"]
    args: list = [ws, *params]
    if not include_superseded:
        sql.append("AND superseded_by IS NULL")
    if tier:
        sql.append("AND tier=%s"); args.append(tier)
    if scope:
        sql.append("AND scope=%s"); args.append(scope)
    sql.append("ORDER BY created_at DESC LIMIT %s OFFSET %s")
    args += [limit, offset]
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(" ".join(sql), args)
        return [dict(r) for r in cur.fetchall()]


def recall(db: DB, *, ws: int, agent_id: str, query: str, top_k: int = 8,
           tier: str | None = None, query_embedding: list[float] | None = None) -> list[dict]:
    """Hybrid recall (BM25 + optional vector → RRF) over memories visible to
    `agent_id`. Reinforces importance of the recalled memories."""
    if not query:
        return []
    bm = _bm25(db, ws, agent_id, query, tier, top_k * 3)
    ann = (_ann(db, ws, agent_id, query_embedding, tier, top_k * 3)
           if (query_embedding and _has_embedding_col(db)) else [])
    fused = _rrf(bm, ann, top_k)
    if not fused:
        return []
    ids = [mid for mid, _ in fused]
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, agent_id, scope, tier, session_id, mkey, title, content,
                              importance, access_count, created_at, last_accessed_at
                       FROM agent_memory WHERE id = ANY(%s::bigint[])""", (ids,))
        rows = {r["id"]: dict(r) for r in cur.fetchall()}
        # reinforce: recalled memories become more durable
        cur.execute("""UPDATE agent_memory
                       SET access_count=access_count+1, last_accessed_at=NOW(),
                           importance=LEAST(importance+%s, %s)
                       WHERE id = ANY(%s::bigint[])""",
                    (_RECALL_BOOST, _IMPORTANCE_CAP, ids))
    out = []
    for mid, score in fused:
        if mid in rows:
            r = rows[mid]; r["score"] = round(score, 4); out.append(r)
    return out


# ─────────────────────────── consolidation ───────────────────────────
def consolidate(db: DB, *, ws: int, agent_id: str, session_id: str = "",
                llm=None, model: str = "") -> dict:
    """Roll up working observations for a session into one episodic memory and
    promote durable facts to the semantic tier. Idempotent: consolidated working
    items are superseded so they are not rolled up twice."""
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, content, content_hash FROM agent_memory
                       WHERE workspace_id=%s AND agent_id=%s AND session_id=%s
                         AND tier='working' AND superseded_by IS NULL
                       ORDER BY created_at""", (ws, agent_id, session_id))
        working = list(cur.fetchall())
    if not working:
        return {"episodic_id": None, "facts": 0, "working_consolidated": 0}

    observations = "\n".join(f"- {w['content']}" for w in working)
    summary_md, facts = _summarize(observations, llm, model)
    episodic = remember(db, ws=ws, agent_id=agent_id, tier="episodic", session_id=session_id,
                        title=f"Session {session_id}".strip(), content=summary_md,
                        importance=1.0, redact_secrets=True)
    # promote durable facts to semantic memory
    for f in facts:
        remember(db, ws=ws, agent_id=agent_id, tier="semantic", content=f,
                 importance=1.2, redact_secrets=True)
    # mark the working observations as consolidated (superseded by the episode)
    ids = [w["id"] for w in working]
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("UPDATE agent_memory SET superseded_by=%s, updated_at=NOW() "
                        "WHERE id = ANY(%s::bigint[])", (episodic["id"], ids))
            for w in working:
                _audit(cur, ws, w["id"], agent_id, "working", "supersede",
                       author="system", reason=f"consolidated into {episodic['id']}",
                       content_hash=w["content_hash"])
    return {"episodic_id": episodic["id"], "facts": len(facts),
            "working_consolidated": len(ids)}


def _summarize(observations: str, llm, model: str) -> tuple[str, list[str]]:
    """Return (episodic_markdown, semantic_facts). Uses the LLM when available,
    otherwise a deterministic raw roll-up (no summarization, no facts)."""
    if llm is None:
        return f"## Session notes\n\n{observations}\n", []
    try:
        from pathlib import Path
        prompt_path = Path(__file__).resolve().parent / "prompts" / "memory_consolidate.txt"
        system = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else (
            "Summarize the observations as Markdown with a '## Summary' section and a "
            "'## Key facts' section of '- ' bullets for durable facts.")
        mid = model or get_config().llm_atlas_model
        res = llm.chat(system=system, user=observations, model=mid, max_tokens=1500)
        text = (res.text or "").strip()
        if not text:
            return f"## Session notes\n\n{observations}\n", []
        return text, _extract_facts(text)
    except Exception as exc:
        log.warning("memory consolidation LLM failed, using raw roll-up: %s", exc)
        return f"## Session notes\n\n{observations}\n", []


def _extract_facts(md: str) -> list[str]:
    """Pull '- '/'* ' bullets that follow a Facts/Decisions heading."""
    facts, capture = [], False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("#"):
            low = s.lstrip("#").strip().lower()
            capture = any(k in low for k in ("key fact", "facts", "decision", "takeaway"))
            continue
        if capture and (s.startswith("- ") or s.startswith("* ")):
            fact = s[2:].strip()
            if fact:
                facts.append(fact)
    return facts


def import_transcript(db: DB, *, ws: int, agent_id: str, transcript, session_id: str = "",
                      consolidate_after: bool = True, llm=None, model: str = "") -> dict:
    """Import a conversation transcript into memory: each turn becomes a working
    observation, then (optionally) the session is consolidated into episodic +
    semantic memory. `transcript` may be a string (one turn per line), a list of
    strings, or a list of {role, text} dicts."""
    turns = _normalize_transcript(transcript)
    observed = 0
    for t in turns:
        if t.strip():
            observe(db, ws=ws, agent_id=agent_id, content=t.strip(), session_id=session_id)
            observed += 1
    res = {"observed": observed}
    if consolidate_after and observed:
        res.update(consolidate(db, ws=ws, agent_id=agent_id, session_id=session_id, llm=llm, model=model))
    return res


def _normalize_transcript(transcript) -> list[str]:
    if isinstance(transcript, str):
        return [ln for ln in transcript.splitlines()]
    out = []
    for item in (transcript or []):
        if isinstance(item, dict):
            role = item.get("role") or item.get("speaker") or ""
            text = item.get("text") or item.get("content") or ""
            out.append(f"{role}: {text}".strip(": ").strip())
        else:
            out.append(str(item))
    return out


# ─────────────────────────── decay / GC ───────────────────────────
def decay_and_gc(db: DB, *, ws: int, agent_id: str | None = None,
                 half_life_days: float | None = None, min_importance: float | None = None,
                 working_cap: int | None = None) -> dict:
    """Evict transient (working/episodic) memories whose time-decayed importance
    has fallen below the floor, and trim the working buffer to its cap. Durable
    tiers (semantic/procedural) are never auto-evicted. Returns evicted ids."""
    cfg = get_config()
    half_life = half_life_days if half_life_days is not None else cfg.memory_decay_half_life_days
    floor = min_importance if min_importance is not None else cfg.memory_min_importance
    cap = working_cap if working_cap is not None else cfg.memory_working_cap
    evicted: list[int] = []
    with db.pool.connection() as conn:
        with conn.transaction(), conn.cursor() as cur:
            # 1) time-decayed importance below floor (transient tiers only)
            sql = ["""SELECT id, agent_id, tier, content_hash FROM agent_memory
                      WHERE workspace_id=%s AND superseded_by IS NULL
                        AND tier IN ('working','episodic')
                        AND importance * power(0.5,
                            EXTRACT(EPOCH FROM (NOW()-last_accessed_at))/86400.0/%s) < %s"""]
            args: list = [ws, max(half_life, 0.0001), floor]
            if agent_id:
                sql.append("AND agent_id=%s"); args.append(agent_id)
            cur.execute(" ".join(sql), args)
            for r in cur.fetchall():
                _audit(cur, ws, r["id"], r["agent_id"], r["tier"], "evict",
                       author="system", reason="decayed below importance floor",
                       content_hash=r["content_hash"])
                evicted.append(r["id"])
            # 2) trim the working buffer to the cap (oldest first), per agent
            cur.execute("""SELECT id, agent_id, content_hash FROM agent_memory m
                           WHERE workspace_id=%s AND tier='working' AND superseded_by IS NULL
                             AND id <> ALL(%s::bigint[])
                             AND (SELECT count(*) FROM agent_memory x
                                  WHERE x.workspace_id=m.workspace_id AND x.agent_id=m.agent_id
                                    AND x.tier='working' AND x.superseded_by IS NULL
                                    AND x.created_at >= m.created_at) > %s""",
                        (ws, evicted or [0], cap))
            for r in cur.fetchall():
                _audit(cur, ws, r["id"], r["agent_id"], "working", "evict",
                       author="system", reason="working buffer over cap",
                       content_hash=r["content_hash"])
                evicted.append(r["id"])
            if evicted:
                cur.execute("DELETE FROM agent_memory WHERE id = ANY(%s::bigint[])", (evicted,))
    return {"evicted": evicted, "count": len(evicted)}


# ─────────────────────────── markdown export ───────────────────────────
def memory_markdown(db: DB, *, ws: int, agent_id: str, limit: int = 500) -> str:
    """Render an agent's memory as a single Markdown digest (canonical form)."""
    rows = list_memory(db, ws=ws, agent_id=agent_id, limit=limit)
    if not rows:
        return f"# Memory — {agent_id}\n\n_(empty)_\n"
    out = [f"# Memory — {agent_id}\n"]
    for t in TIERS:
        group = [r for r in rows if r["tier"] == t]
        if not group:
            continue
        out.append(f"\n## {t.capitalize()}\n")
        for r in group:
            head = r["title"] or r["content"].splitlines()[0][:60]
            out.append(f"### {head}\n\n{r['content']}\n")
    return "\n".join(out)


# ─────────────────────────── internals ───────────────────────────
def _audit(cur, ws, mem_id, agent_id, tier, action, *, author, reason, content_hash):
    cur.execute("""INSERT INTO memory_audit
                   (workspace_id, memory_id, agent_id, tier, action, author, reason, content_hash)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ws, mem_id, agent_id, tier, action, author, reason, content_hash))


def _bm25(db, ws, agent_id, query, tier, limit):
    import re
    fts = get_config().fts_config
    # OR the query terms: recall should surface a memory that matches ANY term
    # (unlike document search, which ANDs). Tokens are word-chars only — safe to
    # pass to to_tsquery as a bound parameter.
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    if not tokens:
        return []
    tsq = " | ".join(tokens)
    vis, vparams = _visibility(agent_id)
    sql = [f"""SELECT id, ts_rank(tsv, to_tsquery('{fts}', %s)) rank
               FROM agent_memory
               WHERE workspace_id=%s AND {vis} AND superseded_by IS NULL
                 AND tsv @@ to_tsquery('{fts}', %s)"""]
    args: list = [tsq, ws, *vparams, tsq]
    if tier:
        sql.append("AND tier=%s"); args.append(tier)
    sql.append("ORDER BY rank DESC LIMIT %s"); args.append(limit)
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute(" ".join(sql), args)
        return [(r["id"], float(r["rank"])) for r in cur.fetchall()]


def _ann(db, ws, agent_id, qemb, tier, limit):
    vec = _vec(qemb)
    vis, vparams = _visibility(agent_id)
    sql = [f"""SELECT id, 1-(embedding <=> %s::vector) sim FROM agent_memory
               WHERE workspace_id=%s AND {vis} AND superseded_by IS NULL
                 AND embedding IS NOT NULL"""]
    args: list = [vec, ws, *vparams]
    if tier:
        sql.append("AND tier=%s"); args.append(tier)
    sql.append("ORDER BY embedding <=> %s::vector LIMIT %s"); args += [vec, limit]
    with db.pool.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(" ".join(sql), args)
            return [(r["id"], float(r["sim"])) for r in cur.fetchall()]
        except Exception as exc:
            log.warning("memory ANN unavailable (%s) — BM25 only", exc)
            return []


def _rrf(a, b, top_k, k=60):
    scores: dict[int, float] = {}
    for lst in (a, b):
        for rank, (mid, _) in enumerate(lst):
            scores[mid] = scores.get(mid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])[:top_k]
