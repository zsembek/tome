"""Pipeline orchestrator: extract→structure→verify→vision→name→split→index→atlas.

Takes file bytes, runs all stages, writes atomically to the DB, refreshes the Atlas.
Each stage writes progress/tokens/faithfulness to the job."""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from contextlib import contextmanager

from tome.config import Config, get_config
from tome.db import DB
from tome.embed import get_embedder
from tome.extract import extract_document
from tome.extract.base import Figure, repair_encoding
from tome.extract import pdfutil
from tome.pipeline import atlas as atlas_mod
from tome.pipeline.chunk import chunk_section
from tome.pipeline.clean import clean
from tome.pipeline.naming import derive_metadata
from tome.pipeline.split import build_sections, split_parts
from tome.pipeline.structure import structure_page
from tome.pipeline.verify import verify
from tome.pipeline.vision import classify_and_describe
from tome.store import store_document_atomic
from tome.storage import get_store, sha256

log = logging.getLogger(__name__)
_FIG_TOKEN = "[[FIGURE_{n:04d}]]"


@contextmanager
def _stage_timer(timings: dict, name: str):
    """Record wall-clock ms for a pipeline stage into `timings` (for per-stage metrics)."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        timings[name] = timings.get(name, 0) + round((time.monotonic() - t0) * 1000)


def _map_concurrent(items, fn, concurrency):
    """Apply `fn` to each item, preserving INPUT order in the output. Runs up to
    `concurrency` calls in parallel threads; serial when concurrency<=1 or <2 items.
    Exceptions propagate (so a failed page fails the job → bounded retry/resume)."""
    items = list(items)
    conc = max(1, int(concurrency or 1))
    if conc == 1 or len(items) <= 1:
        return [fn(it) for it in items]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(conc, len(items))) as ex:
        return list(ex.map(fn, items))


def _resolve_folder_id(db, workspace_id: int, folder_id, folder_path,
                       auto_file: bool, suggested):
    """Decide the document's folder, resiliently.

    folder_id takes priority (exact, no name ambiguity) — BUT only if it still exists in
    this workspace. A stale folder_id (folder deleted, or stale client state) would
    otherwise violate the documents->folders FK and fail the whole job on every retry.
    When the id is missing we fall back to folder_path, then the auto-suggested path,
    then root (None)."""
    if folder_id is not None and db.folder_exists(workspace_id, folder_id):
        return folder_id
    if folder_id is not None:
        log.warning("ingest: folder_id=%s not found in workspace %s — placing at root/path",
                    folder_id, workspace_id)
    if folder_path:
        return db.ensure_folder_path(workspace_id, folder_path)
    if auto_file and suggested:
        return db.ensure_folder_path(workspace_id, suggested)
    return None


def ingest(db: DB, *, workspace_id: int, file_bytes: bytes, filename: str, mime: str,
           folder_path: str | None = None, folder_id: int | None = None,
           auto_file: bool = False, title_override: str | None = None,
           job_id: int | None = None, cfg: Config | None = None) -> int:
    cfg = cfg or get_config()
    # per-workspace settings override env limits (§ settings)
    try:
        ws_settings = db.workspace_settings(workspace_id)
        for k in ("max_section_chars", "min_section_chars", "chunk_tokens",
                  "chunk_overlap", "max_md_chars", "faithfulness_min", "target_lang"):
            if k in ws_settings:
                setattr(cfg, k, ws_settings[k])
    except Exception:
        pass
    tlang = cfg.target_lang
    tok_in = tok_out = 0
    store = get_store(cfg)
    doc_key = sha256(file_bytes)[:16]
    pending_assets: list[dict] = []   # populated after the document is created
    timings: dict[str, int] = {}      # per-stage wall-clock ms (for speed metrics)

    def progress(stage: str, p: float):
        if job_id:
            db.update_job(job_id, stage=stage, progress=p)

    # 0. original into object store
    try:
        src_key = f"sources/{doc_key}/{filename or 'document'}"
        store.put(src_key, file_bytes, mime)
        pending_assets.append({"kind": "source", "object_key": src_key,
                               "mime": mime, "sha": sha256(file_bytes)})
    except Exception as exc:
        log.warning("failed to store original: %s", exc)

    # 1. Extract
    progress("extract", 0.1)
    with _stage_timer(timings, "extract"):
        extracted = extract_document(file_bytes, mime=mime, filename=filename, cfg=cfg)

    # 2-4. Per page: structure → verify → vision (with figure-token substitution)
    progress("structure", 0.3)
    page_mds: list[str] = []
    raw_pages: list[str] = []          # raw extract — basis for document-level faithfulness
    fig_descriptions: dict[str, str] = {}
    fig_counter = 0
    worst_faith = 1.0
    # average extract confidence (if the provider reports it) — an indicator of OCR quality
    page_confidences = [p.confidence for p in extracted.pages if p.confidence is not None]
    extract_confidence = round(sum(page_confidences) / len(page_confidences), 3) if page_confidences else None

    n_pages = max(1, len(extracted.pages))
    is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
    if job_id:
        db.merge_job_payload(job_id, {"pages_total": n_pages})   # for the Jobs view
    # resume: page results already completed in a previous (failed) attempt of this job
    page_results = db.get_page_results(job_id) if job_id else {}

    def _process_page(raw_with_tokens: str, page, fig_map: dict) -> tuple[str, list, float, int, int]:
        """Structure ONE page (text + figures → Markdown). Pure & thread-safe: returns
        (md, page_assets, faith, tokens_in, tokens_out) instead of mutating shared state,
        so pages can run concurrently."""
        ti_total = to_total = 0
        md, ti, to = structure_page(raw_with_tokens, cfg, tlang)
        ti_total += ti; to_total += to
        faith = 1.0
        if raw_with_tokens.strip():
            rep = verify(page.text or "", md, min_score=cfg.faithfulness_min, target_lang=tlang)
            if not rep.passed and cfg.structure_smart and cfg.structure_escalate:
                from tome.llm import get_llm
                from tome.prompts import load_prompt
                try:
                    res = get_llm(cfg).chat(system=load_prompt("structure", TARGET_LANG=tlang),
                                            user=raw_with_tokens, model=cfg.llm_structure_model,
                                            max_tokens=cfg.llm_max_completion_tokens)
                    md2 = res.text.strip(); ti_total += res.tokens_in; to_total += res.tokens_out
                    rep2 = verify(page.text or "", md2, min_score=cfg.faithfulness_min, target_lang=tlang)
                    if rep2.score >= rep.score:
                        md, rep = md2, rep2
                except Exception as exc:
                    log.warning("structure escalation failed: %s", exc)
            # CONTENT-PRESERVATION GUARANTEE: never let structuring drop a page — if the
            # output is drastically shorter than the source, keep the RAW text verbatim.
            src_len = len((page.text or "").strip())
            if src_len > 200 and len(md.strip()) < cfg.structure_min_length_ratio * src_len:
                log.warning("page %d: structured output too short — keeping raw text", page.number)
                md = raw_with_tokens
                rep = verify(page.text or "", md, min_score=cfg.faithfulness_min, target_lang=tlang)
            faith = rep.score
        # figures: crop → classify/describe → store PNG → embed in Markdown
        page_assets: list[dict] = []
        for fn, (token, fig) in enumerate(fig_map.items()):
            block = "\n\n"
            if is_pdf and cfg.vision_enabled:
                try:
                    png = pdfutil.extract_figure_png(file_bytes, fig.page_number - 1, fig.bbox)
                    if png:
                        v = classify_and_describe(png, cfg, tlang)
                        if v.get("informative"):
                            key = f"figures/{doc_key}/p{fig.page_number}_{fn}.png"
                            store.put(key, png, "image/png")
                            page_assets.append({"kind": "figure", "object_key": key,
                                                "fig_class": v.get("fig_class"),
                                                "mime": "image/png", "sha": sha256(png)})
                            desc = v.get("description", "")
                            alt = (fig.caption or desc or "figure")[:80]
                            block = (f"\n\n![{alt}](/v1/assets/{key})\n\n> **Figure:** {desc}\n\n"
                                     if desc else f"\n\n![{alt}](/v1/assets/{key})\n\n")
                except Exception as exc:
                    log.debug("vision fig fail: %s", exc)
            md = md.replace(token, block)
        return md, page_assets, faith, ti_total, to_total

    # Phase A — assign figure tokens deterministically (cheap, sequential) so concurrent
    # page workers never collide on a token id.
    work: list[tuple[int, object, str, dict]] = []
    for pi, page in enumerate(extracted.pages):
        raw = page.text or ""
        raw_pages.append(raw)
        fig_map: dict[str, Figure] = {}
        for fig in page.figures:
            token = _FIG_TOKEN.format(n=fig_counter)
            raw = raw + f"\n\n{token}\n"
            fig_map[token] = fig
            fig_counter += 1
        work.append((pi, page, raw, fig_map))

    # Phase B — reuse completed pages (resume), process the rest CONCURRENTLY.
    page_mds = [""] * len(work)
    to_run: list[tuple[int, object, str, dict]] = []
    for (pi, page, raw, fig_map) in work:
        ck = page_results.get(page.number)
        if ck is not None:                       # RESUME: reuse the already-completed page
            page_mds[pi] = ck["content"]
            pending_assets.extend(ck.get("assets") or [])
            worst_faith = min(worst_faith, ck["faithfulness"] if ck["faithfulness"] is not None else 1.0)
        else:
            to_run.append((pi, page, raw, fig_map))

    _plock = threading.Lock()
    _done = [len(work) - len(to_run)]   # pages already finished (resumed from checkpoints)

    def _worker(item):
        pi, page, raw, fig_map = item
        md, page_assets, faith, ti, to = _process_page(raw, page, fig_map)
        # checkpoint immediately so a crash/restart resumes from here (drives pages_done too)
        db.save_page_result(job_id, page.number, md, page_assets, round(faith, 3))
        # live progress for the floating status widget (advance 0.30 -> 0.55 as pages land)
        with _plock:
            _done[0] += 1
            d = _done[0]
        progress(f"structuring {d}/{n_pages}", round(0.30 + 0.25 * (d / n_pages), 3))
        return pi, md, page_assets, faith, ti, to

    with _stage_timer(timings, "structure"):   # structure + verify + figure-vision, in parallel
        for pi, md, page_assets, faith, ti, to in _map_concurrent(to_run, _worker, cfg.page_concurrency):
            page_mds[pi] = md
            pending_assets.extend(page_assets)
            worst_faith = min(worst_faith, faith)
            tok_in += ti; tok_out += to

    full_md = clean("\n\n".join(page_mds))
    # Final deterministic codepage repair: a mis-decoded CP1251/KOI8-R text layer (broken
    # font) becomes correct Cyrillic here — applied after clean() because the extractor's
    # raw per-page layout can defeat token detection, whereas the cleaned text is reliable.
    _repaired = repair_encoding(full_md)
    if _repaired:
        full_md = _repaired

    # Optional ingestion-time secret/PII redaction (untrusted sources / compliance).
    raw_pages_for_verify = raw_pages
    if cfg.ingest_redact:
        from tome.redact import redact as _redact
        full_md = _redact(full_md)
        raw_pages_for_verify = [_redact(r) for r in raw_pages]  # fair faithfulness compare

    # Document-level faithfulness: the final markdown against the ENTIRE raw extract.
    # This catches losses during clean/split/assembly (not just per-page structure) and
    # is NOT trivially 1.0 under the smart skip. The honesty boundary: completeness is
    # guaranteed RELATIVE to what the extractor pulled out; the quality of the OCR itself
    # is reflected by extract_confidence (if the provider reports it).
    raw_all = "\n\n".join(raw_pages_for_verify)
    if raw_all.strip():
        doc_rep = verify(raw_all, full_md, min_score=cfg.faithfulness_min, target_lang=tlang)
        worst_faith = min(worst_faith, doc_rep.score)
        if not doc_rep.passed:
            log.warning("document below faithfulness threshold: score=%s coverage=%s missing_numbers=%s",
                        doc_rep.score, doc_rep.coverage, doc_rep.missing_numbers[:5])

    # 5. Name
    progress("name", 0.6)
    existing = [f["path"] for f in db.folder_tree(workspace_id)]
    with _stage_timer(timings, "name"):
        meta = derive_metadata(full_md, cfg, tlang, existing, filename)
    if title_override:
        meta["title"] = title_override   # honor a caller-supplied title (ready-Markdown ingest)
    meta["source_object_key"] = src_key  # persist the link to the stored original (enables reindex)
    # prefer the language detected by the extractor's AI pre-analysis (the OCR was tuned
    # to it), then naming, then a script-based guess
    detected_lang = (extracted.metadata.get("language") or "").strip()
    language = detected_lang or (meta.get("language") or "").strip() or _guess_lang(full_md)

    # folder placement (folder_id takes priority — exact, no name ambiguity)
    fid = _resolve_folder_id(db, workspace_id, folder_id, folder_path, auto_file,
                             meta.get("suggested_folder_path"))

    # 5.5 Reimport: skip / conflict-pending / replace (§6-bis)
    content_hash = hashlib.sha256(full_md.encode("utf-8")).hexdigest()
    existing = db.find_document(workspace_id, fid, filename)
    if existing:
        unchanged = (existing["content_hash"] == content_hash
                     and existing["pipeline_version"] == cfg.pipeline_version)
        if unchanged:
            if job_id:
                db.update_job(job_id, status="done", stage="unchanged", progress=1.0,
                              document_id=existing["id"])
                db.clear_page_results(job_id)
            return existing["id"]
        if db.manual_edit_count(existing["id"]) > 0:
            # manual edits exist → do NOT overwrite silently: pending version + diff for confirmation
            snap_key = f"pending/{doc_key}/{content_hash[:12]}.md"
            try:
                store.put(snap_key, full_md.encode("utf-8"), "text/markdown")
            except Exception:
                pass
            vno = db.create_pending_version(existing["id"], snapshot_key=snap_key,
                                            content_hash=content_hash,
                                            pipeline_version=cfg.pipeline_version,
                                            faith=round(worst_faith, 3))
            if job_id:
                db.update_job(job_id, status="done", stage="conflict_pending", progress=1.0,
                              document_id=existing["id"])
                db.merge_job_payload(job_id, {"conflict": True, "pending_version": vno,
                                              "snapshot_key": snap_key})
                db.clear_page_results(job_id)
            return existing["id"]
        # no manual edits → safe to replace (delete the old one, recreate)
        from tome.edit import delete_document as _del
        _del(db, existing["id"])

    # 6. Split
    progress("split", 0.7)
    sections = build_sections(full_md, max_chars=cfg.max_section_chars,
                              min_chars=cfg.min_section_chars)
    parts = split_parts(full_md, cfg.max_md_chars)

    # 7. Index (retrieval chunks + embeddings)
    progress("index", 0.85)
    chunks_by_sec: dict[int, list] = {}
    for s in sections:
        chs = chunk_section(s.order_index, s.content,
                            chunk_tokens=cfg.chunk_tokens, overlap=cfg.chunk_overlap)
        if chs:
            chunks_by_sec[s.order_index] = chs

    embeddings_by_chunk = None
    embed_model_id = ""
    embedder = get_embedder(cfg)
    if embedder:
        try:
            flat = [(soi, ch) for soi, chs in chunks_by_sec.items() for ch in chs]
            with _stage_timer(timings, "embed"):
                vectors = embedder.embed([ch.text for _, ch in flat])
            embeddings_by_chunk = {(soi, ch.ordinal): v for (soi, ch), v in zip(flat, vectors)}
            embed_model_id = embedder.model_id
            if vectors:
                db.ensure_vector_index(len(vectors[0]))
        except Exception as exc:
            log.warning("embeddings skipped: %s", exc)

    meta.update(source_filename=filename, mime_type=mime, extractor=extracted.extractor,
                content_hash=content_hash, pipeline_version=cfg.pipeline_version,
                faithfulness_score=round(worst_faith, 3), embed_model_id=embed_model_id)

    with _stage_timer(timings, "persist"):
        doc_id = store_document_atomic(
            db, workspace_id=workspace_id, folder_id=fid, meta=meta, parts=parts,
            sections=sections, chunks_by_section=chunks_by_sec,
            embeddings_by_chunk=embeddings_by_chunk, language=language)

    # record assets (original + images) for bookkeeping/GC/serving
    for a in pending_assets:
        try:
            db.insert_asset(document_id=doc_id, kind=a["kind"], object_key=a["object_key"],
                            fig_class=a.get("fig_class"), mime=a.get("mime", ""),
                            sha=a.get("sha", ""))
        except Exception as exc:
            log.debug("insert_asset fail: %s", exc)

    # 8. Knowledge graph (derived entities + co-occurrence) — never fails ingest
    if cfg.graph_enabled:
        try:
            from tome.graph import build_graph_for_document
            build_graph_for_document(db, workspace_id, doc_id)
        except Exception as exc:
            log.debug("graph build skipped: %s", exc)

    # 9. Atlas (delta for the folder)
    progress("atlas", 0.95)
    with _stage_timer(timings, "atlas"):
        if fid:
            _refresh_atlas_node(db, workspace_id, fid, cfg, tlang)
        _refresh_atlas_index(db, workspace_id)

    if job_id:
        db.update_job(job_id, status="done", stage="done", progress=1.0,
                      document_id=doc_id, tokens_in=tok_in, tokens_out=tok_out,
                      faithfulness_score=round(worst_faith, 3))
        # MERGE (don't replace) so filename / pages_total / timings survive for the Jobs view
        db.merge_job_payload(job_id, {"extract_confidence": extract_confidence,
                                      "extractor": extracted.extractor,
                                      "timings_ms": timings})
        db.clear_page_results(job_id)   # success → drop per-page checkpoints
    # event for webhooks
    try:
        db.emit_event(workspace_id, "document.ready",
                      {"document_id": doc_id, "title": meta["title"],
                       "faithfulness": round(worst_faith, 3)})
    except Exception:
        pass
    return doc_id


def _refresh_atlas_node(db: DB, ws: int, folder_id: int, cfg: Config, tlang: str):
    tree = {f["id"]: f for f in db.folder_tree(ws)}
    f = tree.get(folder_id)
    if not f:
        return
    docs = [{"title": d["title"], "summary": d.get("summary", ""),
             "section_count": d.get("section_count", 0)} for d in db.list_documents(folder_id)]
    md = atlas_mod.build_folder_node(f["name"], f.get("description", ""), docs, cfg, tlang)
    db.upsert_atlas(ws, f"folder:{folder_id}", md)


def refresh_atlas_index(db: DB, ws: int):
    """Full Atlas index over ALL folders (indented by nesting depth), not just the
    top level — so that nested/empty folders are visible to the agent."""
    tree = db.folder_tree(ws)  # sorted by path → natural hierarchy
    md = atlas_mod.build_index([{"name": f["name"], "path": f.get("path", ""),
                                 "description": f.get("description", ""),
                                 "document_count": f.get("doc_count", 0)} for f in tree])
    db.upsert_atlas(ws, "index", md)


# backward compatibility
_refresh_atlas_index = refresh_atlas_index


def _guess_lang(text: str) -> str:
    if re.search(r"[\u0400-\u04ff]", text):    # Cyrillic block
        return "ru"
    if re.search(r"[\u4e00-\u9fff]", text):    # CJK Unified Ideographs
        return "zh"
    return "en"
