"""Tome Gateway: FastAPI REST + Library UI + background import worker."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (Body, Depends, FastAPI, File, Form, Header, HTTPException,
                     Query, Request, UploadFile)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tome.config import get_config
from tome.db import ConflictError
from tome.embed import get_embedder
from tome.pipeline.run import ingest
from tome.store import hybrid_search
from tome.storage import get_store
from tome import edit as ed
from api.deps import (current_token, current_user, current_workspace, get_db,
                      init_db, require_admin, require_auth)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("tome.api")

_STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    db = init_db()
    cfg = get_config()
    # seed the first admin from env (only if there are no users yet)
    if cfg.admin_email and cfg.admin_password and db.count_users() == 0:
        try:
            db.create_user(current_workspace(), cfg.admin_email, cfg.admin_password, role="admin")
            log.info("seeded admin user '%s' from env", cfg.admin_email)
        except Exception as exc:
            log.warning("admin seed failed: %s", exc)
    try:
        n = db.purge_expired_sessions()
        if n:
            log.info("purged %d expired sessions", n)
    except Exception:
        pass
    # access-state warnings
    if cfg.tome_open:
        log.warning(
            "=" * 70 + "\n"
            "  WARNING: TOME_OPEN=true — OPEN mode with NO authentication.\n"
            "  Anyone who can reach the port gets FULL access (admin).\n"
            "  Use ONLY on localhost / a trusted network.\n" + "=" * 70)
    elif db.count_users() == 0 and not cfg.api_key:
        log.warning(
            "Tome: no users yet. Create the first administrator:\n"
            "  POST /v1/auth/bootstrap {email, password}  (or set TOME_ADMIN_EMAIL/PASSWORD in .env)")
    if cfg.run_inprocess_worker:
        _start_worker()
    yield
    # ── shutdown ── close the DB connection pool cleanly (no dangling threads)
    from api.deps import close_db
    close_db()


app = FastAPI(title="Tome", version="0.1.0",
              description="Agent-native knowledge OS — REST API", lifespan=lifespan)


# ─────────────────────────── Folders ───────────────────────────
@app.get("/v1/folders", dependencies=[Depends(require_auth)])
def list_folders(parent_id: int | None = None, lazy: bool = False):
    db = get_db()
    if lazy:
        # lazy tree: only the direct children of parent_id (None → root)
        return {"folders": db.folder_children(current_workspace(), parent_id)}
    return {"folders": db.folder_tree(current_workspace())}


@app.post("/v1/folders", dependencies=[Depends(require_auth)])
def create_folder(path: str = Body(..., embed=True),
                  description: str = Body("", embed=True)):
    db = get_db()
    ws = current_workspace()
    fid = db.ensure_folder_path(ws, path)
    if description:
        try:
            ed.rename_folder(db, fid, description=description)
        except Exception:
            pass
    try:
        from tome.pipeline.run import refresh_atlas_index
        refresh_atlas_index(db, ws)
    except Exception:
        pass
    return {"folder_id": fid, "path": path}


# ─────────────────────────── Documents ─────────────────────────
@app.post("/v1/documents", dependencies=[Depends(require_auth)])
async def upload_document(
    file: UploadFile = File(...),
    folder_path: str | None = Form(None),
    auto_file: bool = Form(False),
):
    db = get_db()
    ws = current_workspace()
    data = await file.read()
    job_id = db.create_job(ws, {"filename": file.filename,
                                "folder_path": folder_path, "auto_file": auto_file,
                                "mime": file.content_type or ""})
    # stage the bytes to a temp area for the worker
    _STAGE.mkdir(parents=True, exist_ok=True)
    (_STAGE / f"{job_id}.bin").write_bytes(data)
    (_STAGE / f"{job_id}.meta").write_text(
        f"{file.filename}\n{file.content_type or ''}\n{folder_path or ''}\n{int(auto_file)}",
        encoding="utf-8")
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_auth)])
def get_job(job_id: int):
    job = get_db().get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.get("/v1/folders/{folder_id}/documents", dependencies=[Depends(require_auth)])
def folder_documents(folder_id: int, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
    return {"documents": get_db().list_documents(folder_id, limit=limit, offset=offset),
            "limit": limit, "offset": offset}


@app.get("/v1/documents/{doc_id}", dependencies=[Depends(require_auth)])
def get_document(doc_id: int):
    doc = get_db().get_document(doc_id)
    if not doc:
        raise HTTPException(404, "document not found")
    return doc


@app.get("/v1/documents/{doc_id}/sections", dependencies=[Depends(require_auth)])
def doc_sections(doc_id: int, depth: int = Query(2, ge=1, le=6),
                 parent_section_id: int | None = None):
    return {"sections": get_db().list_sections(doc_id, depth, parent_section_id)}


@app.get("/v1/documents/{doc_id}/content", dependencies=[Depends(require_auth)])
def doc_content(doc_id: int, parts: str | None = None):
    plist = [int(x) for x in parts.split(",")] if parts else None
    rows = get_db().get_document_parts(doc_id, plist)
    return {"markdown": "\n\n".join(r["content"] for r in rows),
            "parts_returned": [r["part_number"] for r in rows]}


# ─────────────────────────── Sections ──────────────────────────
@app.get("/v1/sections/{section_id}", dependencies=[Depends(require_auth)])
def get_section(section_id: int, subsections: bool = True):
    db = get_db()
    row = db.get_section(section_id)
    if not row:
        raise HTTPException(404, "section not found")
    if not subsections:
        md = f"{'#'*row['level']} {row['heading']}\n\n{row['content']}"
        return {"section_id": section_id, "heading": row["heading"],
                "markdown": md, "rev": row["rev"]}
    tree = db.get_section_subtree(section_id)
    md = "\n\n".join(f"{'#'*r['level']} {r['heading']}\n\n{r['content']}".rstrip() for r in tree)
    return {"section_id": section_id, "heading": row["heading"],
            "markdown": md.strip() + "\n", "rev": row["rev"]}


@app.patch("/v1/sections/{section_id}", dependencies=[Depends(require_auth)])
def patch_section(section_id: int, content: str = Body(..., embed=True),
                  rev: int | None = Body(None, embed=True)):
    try:
        return get_db().update_section(section_id, content, rev=rev, author="user")
    except ConflictError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))


# ─────────────────────────── Search / Atlas ────────────────────
@app.get("/v1/search", dependencies=[Depends(require_auth)])
def search(q: str, mode: str = "hybrid", top_k: int = Query(10, ge=1, le=50)):
    db = get_db(); cfg = get_config()
    qemb = None
    if mode in ("hybrid", "vector"):
        emb = get_embedder(cfg)
        if emb:
            try:
                qemb = emb.embed([q])[0]
            except Exception:
                qemb = None
    res = hybrid_search(db, workspace_id=current_workspace(), query=q,
                        query_embedding=qemb, top_k=top_k, mode=mode)
    return {"results": res}


@app.get("/v1/atlas", dependencies=[Depends(require_auth)])
def get_atlas(scope: str = "index"):
    return {"scope": scope, "markdown": get_db().get_atlas(current_workspace(), scope)}


@app.get("/v1/extractors", dependencies=[Depends(require_auth)])
def list_extractors_ep():
    """Catalog of pluggable extractors with verified/experimental status + pip extra."""
    from tome.extract.registry import list_extractors
    return {"extractors": list_extractors()}


@app.get("/v1/documents/{doc_id}/section_by_heading", dependencies=[Depends(require_auth)])
def section_by_heading(doc_id: int, heading: str):
    row = ed.get_section_by_heading(get_db(), doc_id, heading)
    if not row:
        return {"error": "not found", "did_you_mean": ed.similar_headings(get_db(), doc_id, heading)}
    return get_section(row["id"], subsections=True)


# ─────────────────────────── Section editing ───────────────────
@app.post("/v1/documents/{doc_id}/sections", dependencies=[Depends(require_auth)])
def add_section(doc_id: int, heading: str = Body(...), content: str = Body(""),
                level: int = Body(2), after_section_id: int | None = Body(None)):
    sid = ed.insert_section(get_db(), doc_id, after_section_id, heading, content, level)
    return {"section_id": sid}


@app.delete("/v1/sections/{section_id}", dependencies=[Depends(require_auth)])
def remove_section(section_id: int):
    ed.delete_section(get_db(), section_id)
    return {"deleted": section_id}


@app.post("/v1/sections/{section_id}/move", dependencies=[Depends(require_auth)])
def move_section(section_id: int, new_parent_id: int | None = Body(None),
                 after_section_id: int | None = Body(None)):
    ed.move_section(get_db(), section_id, new_parent_id, after_section_id)
    return {"moved": section_id}


@app.post("/v1/sections/{section_id}/split", dependencies=[Depends(require_auth)])
def do_split(section_id: int, at: int = Body(..., embed=True)):
    nid = ed.split_section(get_db(), section_id, at)
    return {"new_section_id": nid}


@app.post("/v1/sections/merge", dependencies=[Depends(require_auth)])
def do_merge(section_ids: list[int] = Body(..., embed=True)):
    sid = ed.merge_sections(get_db(), section_ids)
    return {"merged_into": sid}


@app.get("/v1/sections/{section_id}/revisions", dependencies=[Depends(require_auth)])
def section_revisions(section_id: int):
    return {"revisions": ed.list_section_revisions(get_db(), section_id)}


# ─────────────────────────── Document / folder ops ─────────────
@app.patch("/v1/documents/{doc_id}", dependencies=[Depends(require_auth)])
def patch_document(doc_id: int, title: str | None = Body(None),
                   tags: list[str] | None = Body(None), folder_path: str | None = Body(None)):
    ed.update_document(get_db(), doc_id, title=title, tags=tags, folder_path=folder_path,
                       workspace_id=current_workspace())
    return {"updated": doc_id}


@app.delete("/v1/documents/{doc_id}", dependencies=[Depends(require_auth)])
def remove_document(doc_id: int):
    ed.delete_document(get_db(), doc_id)
    return {"deleted": doc_id}


@app.get("/v1/documents/{doc_id}/versions", dependencies=[Depends(require_auth)])
def doc_versions(doc_id: int):
    return {"versions": ed.list_versions(get_db(), doc_id)}


@app.get("/v1/documents/{doc_id}/conflict", dependencies=[Depends(require_auth)])
def doc_conflict(doc_id: int):
    db = get_db()
    pend = db.get_pending_version(doc_id)
    if not pend:
        return {"conflict": False}
    new_md = get_store().get(pend["snapshot_object_key"]) if pend["snapshot_object_key"] else None
    cur_rows = db.get_document_parts(doc_id, None)
    return {"conflict": True, "pending_version": pend["version_no"],
            "current_markdown": "\n\n".join(r["content"] for r in cur_rows),
            "incoming_markdown": (new_md or b"").decode("utf-8", "replace")}


@app.post("/v1/documents/{doc_id}/conflict/resolve", dependencies=[Depends(require_auth)])
def resolve_conflict(doc_id: int, action: str = Body(..., embed=True)):
    """action: keep_current | take_incoming"""
    db = get_db()
    pend = db.get_pending_version(doc_id)
    if not pend:
        raise HTTPException(404, "no pending conflict")
    if action == "keep_current":
        db.discard_pending(doc_id)
        return {"resolved": "kept current"}
    if action == "take_incoming":
        md = get_store().get(pend["snapshot_object_key"])
        if not md:
            raise HTTPException(500, "incoming snapshot missing")
        meta = db.get_document(doc_id)
        ed.delete_document(db, doc_id)
        new_id = ingest(db, workspace_id=current_workspace(),
                        file_bytes=md, filename=meta["source_filename"],
                        mime="text/markdown", folder_path=None)
        return {"resolved": "took incoming", "new_document_id": new_id}
    raise HTTPException(400, "action must be keep_current|take_incoming")


@app.get("/v1/documents/{doc_id}/conflict/sections", dependencies=[Depends(require_auth)])
def conflict_sections(doc_id: int):
    """Per-section 3-way diff (current vs incoming) for granular resolution."""
    from tome.conflict import diff_sections
    return diff_sections(get_db(), doc_id)


@app.post("/v1/documents/{doc_id}/conflict/resolve_sections", dependencies=[Depends(require_auth)])
def resolve_conflict_sections(doc_id: int, choices: dict = Body(..., embed=True)):
    """choices: {heading: 'keep_manual'|'take_import'} — applies the choice per section."""
    from tome.conflict import resolve_sections
    db = get_db()
    if not db.get_pending_version(doc_id):
        raise HTTPException(404, "no pending conflict")
    return resolve_sections(db, doc_id, choices)


@app.patch("/v1/folders/{folder_id}", dependencies=[Depends(require_auth)])
def patch_folder(folder_id: int, name: str | None = Body(None),
                 description: str | None = Body(None)):
    ed.rename_folder(get_db(), folder_id, name=name, description=description)
    return {"updated": folder_id}


@app.post("/v1/folders/{folder_id}/move", dependencies=[Depends(require_auth)])
def move_folder_ep(folder_id: int, new_parent_id: int | None = Body(None, embed=True)):
    ed.move_folder(get_db(), folder_id, new_parent_id)
    return {"moved": folder_id}


@app.delete("/v1/folders/{folder_id}", dependencies=[Depends(require_auth)])
def remove_folder(folder_id: int):
    ed.delete_folder(get_db(), folder_id)
    return {"deleted": folder_id}


# ─────────────────────────── Assets ────────────────────────────
def _valid_key(key: str) -> bool:
    return not (".." in key.split("/") or key.startswith(("/", "\\")) or "\x00" in key)


@app.post("/v1/assets/sign", dependencies=[Depends(require_auth)])
def sign_assets(keys: list[str] = Body(..., embed=True), ttl: int = Body(600, embed=True)):
    """Issue short-lived signed URLs for images (for <img src>).
    Requires read access; the URLs are valid for ttl seconds (default 10 min)."""
    from tome.signing import signed_url
    ttl = max(30, min(int(ttl), 3600))
    out = {k: signed_url(k, ttl) for k in keys if _valid_key(k)}
    return {"signed": out, "ttl": ttl}


@app.get("/v1/assets/{key:path}")
def get_asset(key: str, request: Request,
              exp: int | None = None, sig: str | None = None,
              authorization: str | None = Header(default=None)):
    # defense-in-depth: reject traversal keys explicitly before touching the store
    if not _valid_key(key):
        raise HTTPException(400, "invalid asset key")
    # Access: either a valid short-lived signature, or a Bearer token with read scope.
    from tome.signing import verify as _verify_sig
    authorized = _verify_sig(key, exp, sig)
    if not authorized:
        from api.deps import _resolve_scopes, _token
        authorized = "read" in _resolve_scopes(_token(authorization))
    if not authorized:
        raise HTTPException(401, "authentication required")
    data = get_store().get(key)
    if data is None:
        raise HTTPException(404, "asset not found")
    asset = get_db().get_asset_by_key(key)
    mime = (asset or {}).get("mime") or "application/octet-stream"
    from fastapi import Response
    return Response(content=data, media_type=mime)


# ─────────────────────────── Health / usage ────────────────────
@app.get("/health")
def health():
    db = get_db()
    return {"status": "ok", "schema_ready": db.schema_ready(), "pgvector": db.has_vector()}


@app.get("/v1/eval", dependencies=[Depends(require_auth)])
def eval_metrics():
    from tome.evalkit import corpus_faithfulness
    return corpus_faithfulness(get_db())


@app.get("/v1/usage", dependencies=[Depends(require_auth)])
def usage():
    db = get_db()
    with db.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT count(*) docs, COALESCE(SUM(total_chars),0) chars
                       FROM documents WHERE workspace_id=%s""", (current_workspace(),))
        d = cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(tokens_in),0) ti, COALESCE(SUM(tokens_out),0) to_ FROM ingestion_jobs")
        t = cur.fetchone()
    return {"documents": d["docs"], "total_chars": d["chars"],
            "tokens_in": t["ti"], "tokens_out": t["to_"]}


# ─────────────────────────── Export ────────────────────────────
def _disposition(name: str) -> str:
    """Content-Disposition with RFC 5987 for non-ASCII names (Cyrillic, etc.)."""
    from urllib.parse import quote
    ascii_fallback = name.encode("ascii", "ignore").decode() or "export.zip"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(name)}"


@app.get("/v1/documents/{doc_id}/export", dependencies=[Depends(require_auth)])
def export_document(doc_id: int):
    from tome.export import export_document_bytes
    from fastapi.responses import Response
    try:
        name, data = export_document_bytes(get_db(), doc_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": _disposition(name)})


@app.get("/v1/folders/{folder_id}/export", dependencies=[Depends(require_auth)])
def export_folder(folder_id: int):
    from tome.export import export_folder_bytes
    from fastapi.responses import Response
    try:
        name, data = export_folder_bytes(get_db(), current_workspace(), folder_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": _disposition(name)})


# ─────────────────────────── Admin: API keys / webhooks ────────
@app.post("/v1/api-keys", dependencies=[Depends(require_admin)])
def create_api_key(scopes: list[str] = Body(["read"], embed=True)):
    bad = set(scopes) - {"read", "write", "admin"}
    if bad:
        raise HTTPException(400, f"unknown scopes: {bad}")
    kid, token = get_db().create_api_key(current_workspace(), scopes)
    return {"id": kid, "api_key": token, "scopes": scopes,
            "note": "this key is shown once — store it now"}


@app.get("/v1/api-keys", dependencies=[Depends(require_admin)])
def list_api_keys():
    return {"keys": get_db().list_api_keys(current_workspace())}


@app.delete("/v1/api-keys/{key_id}", dependencies=[Depends(require_admin)])
def delete_api_key(key_id: int):
    get_db().delete_api_key(current_workspace(), key_id)
    return {"deleted": key_id}


@app.post("/v1/webhooks", dependencies=[Depends(require_admin)])
def create_webhook(url: str = Body(..., embed=True),
                   events: list[str] = Body(..., embed=True),
                   secret: str = Body("", embed=True)):
    wid = get_db().create_webhook(current_workspace(), url, events, secret)
    return {"id": wid, "url": url, "events": events}


@app.get("/v1/webhooks", dependencies=[Depends(require_admin)])
def list_webhooks():
    return {"webhooks": get_db().list_webhooks(current_workspace())}


@app.delete("/v1/webhooks/{wid}", dependencies=[Depends(require_admin)])
def delete_webhook(wid: int):
    get_db().delete_webhook(current_workspace(), wid)
    return {"deleted": wid}


# ─────────────────────────── Auth / Users ──────────────────────
@app.get("/v1/auth/status")
def auth_status():
    """Public: tells the frontend what to show — login, bootstrap, or nothing (open)."""
    cfg = get_config(); db = get_db()
    return {"open_mode": cfg.tome_open,
            "needs_bootstrap": (not cfg.tome_open) and db.count_users() == 0,
            "master_key_enabled": bool(cfg.api_key)}


@app.post("/v1/auth/bootstrap")
def auth_bootstrap(email: str = Body(..., embed=True), password: str = Body(..., embed=True)):
    """Create the FIRST administrator. Available only while no users exist."""
    db = get_db()
    if db.count_users() > 0:
        raise HTTPException(403, "bootstrap disabled: users already exist")
    if len(password) < 8:
        raise HTTPException(400, "password too short (min 8 chars)")
    user = db.create_user(current_workspace(), email, password, role="admin")
    token = db.create_session(user["id"], get_config().session_ttl_hours)
    return {"token": token, "user": {"email": user["email"], "role": user["role"]}}


@app.post("/v1/auth/login")
def auth_login(email: str = Body(..., embed=True), password: str = Body(..., embed=True)):
    db = get_db()
    u = db.verify_login(current_workspace(), email, password)
    if not u:
        raise HTTPException(401, "invalid credentials")
    token = db.create_session(u["id"], get_config().session_ttl_hours)
    return {"token": token, "user": {"email": u["email"], "role": u["role"]}}


@app.post("/v1/auth/logout")
def auth_logout(token: str = Depends(current_token)):
    get_db().delete_session(token)
    return {"ok": True}


@app.get("/v1/auth/me")
def auth_me(user: dict = Depends(current_user)):
    return user


def _last_active_admin(db, ws: int, uid: int) -> bool:
    admins = [u for u in db.list_users(ws) if u["role"] == "admin" and not u["disabled"]]
    return len(admins) == 1 and admins[0]["id"] == uid


@app.get("/v1/users", dependencies=[Depends(require_admin)])
def list_users():
    return {"users": get_db().list_users(current_workspace())}


@app.post("/v1/users", dependencies=[Depends(require_admin)])
def create_user_ep(email: str = Body(...), password: str = Body(...),
                   role: str = Body("viewer")):
    import psycopg
    if len(password) < 8:
        raise HTTPException(400, "password too short (min 8 chars)")
    try:
        return get_db().create_user(current_workspace(), email, password, role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "user with this email already exists")


@app.patch("/v1/users/{uid}", dependencies=[Depends(require_admin)])
def update_user_ep(uid: int, role: str | None = Body(None),
                   password: str | None = Body(None), disabled: bool | None = Body(None)):
    db = get_db(); ws = current_workspace()
    if password is not None and len(password) < 8:
        raise HTTPException(400, "password too short (min 8 chars)")
    if ((role is not None and role != "admin") or disabled) and _last_active_admin(db, ws, uid):
        raise HTTPException(400, "cannot demote/disable the last active admin")
    try:
        db.update_user(ws, uid, role=role, password=password, disabled=disabled)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"updated": uid}


@app.delete("/v1/users/{uid}", dependencies=[Depends(require_admin)])
def delete_user_ep(uid: int):
    db = get_db(); ws = current_workspace()
    if _last_active_admin(db, ws, uid):
        raise HTTPException(400, "cannot delete the last active admin")
    db.delete_user(ws, uid)
    return {"deleted": uid}


# ─────────────────────────── Library UI ────────────────────────
if _STATIC.exists():
    app.mount("/ui", StaticFiles(directory=str(_STATIC), html=True), name="ui")


@app.get("/")
def root():
    idx = _STATIC / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    # The Library UI runs as a separate service (webui, default :3000); the gateway
    # itself only serves the API. Advertise the docs, not an unmounted /ui path.
    return JSONResponse({"service": "tome", "docs": "/docs", "openapi": "/openapi.json"})


# ─────────────────────────── Worker (in-process) ───────────────
_STAGE = Path(__file__).resolve().parent.parent / "_stage"
_worker_started = False


def _start_worker():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
    log.info("in-process worker started")


def _worker_loop():
    import time
    db = get_db()
    cfg = get_config()
    db.requeue_stale_jobs(cfg.job_stale_minutes)   # requeue dead jobs from a previous process
    last_sweep = time.monotonic()
    while True:
        jid = None
        try:
            job = db.next_queued_job()
            if not job:
                if time.monotonic() - last_sweep > 60:
                    db.requeue_stale_jobs(cfg.job_stale_minutes); last_sweep = time.monotonic()
                time.sleep(2)
                continue
            jid = job["id"]
            binp = _STAGE / f"{jid}.bin"
            metap = _STAGE / f"{jid}.meta"
            try:
                if not binp.exists():
                    db.update_job(jid, status="error", error="staged file missing")
                    continue
                data = binp.read_bytes()
                fn, mime, folder, autof = (metap.read_text(encoding="utf-8").split("\n") + ["", "", "", "0"])[:4]
                ingest(db, workspace_id=current_workspace(), file_bytes=data,
                       filename=fn, mime=mime, folder_path=(folder or None),
                       auto_file=(autof == "1"), job_id=jid)
            finally:
                binp.unlink(missing_ok=True); metap.unlink(missing_ok=True)
        except Exception as exc:
            log.exception("worker error: %s", exc)
            if jid is not None:
                try:
                    db.update_job(jid, status="error", error=str(exc)[:2000])
                except Exception:
                    pass
            time.sleep(2)
