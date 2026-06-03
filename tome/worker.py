"""Standalone worker: pulls import jobs from the DB queue and runs the pipeline.
Can be scaled with separate containers. Uses a shared staging volume."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import json

import httpx

from tome.config import get_config
from tome.db import DB
from tome.pipeline.run import ingest
from tome.storage import get_store
from tome.webhooks import is_safe_webhook_url, parse_allow_hosts, sign_webhook

log = logging.getLogger("tome.worker")
_STAGE = Path(__file__).resolve().parent.parent / "_stage"


def process_outbox(db: DB) -> int:
    """Executes deferred operations: deleting objects from the store, delivering webhooks.
    Guarantees consistency between the DB and the object store."""
    items = db.next_outbox(limit=50)
    store = get_store()
    n = 0
    for it in items:
        payload = it["payload"] if isinstance(it["payload"], dict) else json.loads(it["payload"] or "{}")
        try:
            if it["aggregate"] == "asset" and it["op"] == "delete":
                store.delete(payload.get("key", ""))
            elif it["aggregate"] == "webhook" and it["op"] == "deliver":
                url = payload.get("url", "")
                allow = parse_allow_hosts(get_config().webhook_allow_hosts)
                if not is_safe_webhook_url(url, allow_hosts=allow):
                    log.warning("webhook %s blocked (unsafe / SSRF url: %s)", it["id"], url)
                    db.mark_outbox(it["id"], "failed")
                    continue
                body_bytes = json.dumps(payload.get("body", {})).encode("utf-8")
                headers = {"Content-Type": "application/json",
                           "X-Tome-Event": payload.get("event", "")}
                sig = sign_webhook(body_bytes, payload.get("secret", ""))
                if sig:
                    headers["X-Tome-Signature"] = sig
                with httpx.Client(timeout=10) as c:
                    c.post(url, content=body_bytes, headers=headers).raise_for_status()
            db.mark_outbox(it["id"], "done")
            n += 1
        except Exception as exc:
            log.warning("outbox %s failed: %s", it["id"], exc)
            db.mark_outbox(it["id"], "pending" if it["attempts"] < 5 else "failed")
    return n


MAX_ATTEMPTS = 3   # bounded retry budget; each retry resumes from the last good page


def run_once(db: DB) -> bool:
    job = db.next_queued_job()
    if not job:
        return False
    jid = job["id"]
    binp, metap = _STAGE / f"{jid}.bin", _STAGE / f"{jid}.meta"
    if not binp.exists():
        db.update_job(jid, status="error", error="staged file missing")
        db.clear_page_results(jid)
        return True
    try:
        data = binp.read_bytes()
        fn, mime, folder, autof, fid = (
            metap.read_text(encoding="utf-8").split("\n") + ["", "", "", "0", ""])[:5]
        ws = db.default_workspace()
        ingest(db, workspace_id=ws, file_bytes=data, filename=fn, mime=mime,
               folder_path=(folder or None), folder_id=(int(fid) if fid.strip() else None),
               auto_file=(autof == "1"), job_id=jid)
    except Exception as exc:
        log.exception("job %s failed", jid)
        attempts = db.bump_job_attempts(jid)
        if attempts >= MAX_ATTEMPTS:
            db.update_job(jid, status="error", error=f"failed after {attempts} attempts: {exc}"[:2000])
            db.clear_page_results(jid)
            binp.unlink(missing_ok=True); metap.unlink(missing_ok=True)
        else:
            # keep staged bytes + per-page checkpoints → next pickup RESUMES from the failed page
            db.update_job(jid, status="queued", stage="retry", error=f"retry {attempts}: {exc}"[:2000])
        return True
    # success: ingest already marked the job done — clean up the stage
    binp.unlink(missing_ok=True); metap.unlink(missing_ok=True)
    return True


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    cfg = get_config()
    db = DB(cfg)
    if not db.schema_ready():
        db.init_schema()
    # at startup, recover "dead" jobs from a previously crashed worker
    requeued = db.requeue_stale_jobs(cfg.job_stale_minutes)
    if requeued:
        log.info("requeued stale jobs: %d", requeued)
    log.info("worker started (concurrency via N containers)")
    last_sweep = time.monotonic()
    while True:
        did = run_once(db)
        out = process_outbox(db)
        # periodically (once a minute) requeue stale jobs
        if time.monotonic() - last_sweep > 60:
            db.requeue_stale_jobs(cfg.job_stale_minutes)
            last_sweep = time.monotonic()
        if not did and not out:
            time.sleep(2)


if __name__ == "__main__":
    main()
