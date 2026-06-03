"""Crash/restart recovery: a job that was 'running' when its worker died must be
reclaimed quickly (heartbeat lease, not a 30-min timeout) and resume from the last
per-page checkpoint — so a server rebuild never leaves ingestion stuck forever."""
import pytest

pytestmark = pytest.mark.integration


def _age_job(db, jid, seconds):
    """Force a job's heartbeat (updated_at) into the past."""
    with db.pool.connection() as c, c.cursor() as cur:
        cur.execute("UPDATE ingestion_jobs SET updated_at = NOW() - (%s||' seconds')::interval "
                    "WHERE id=%s", (str(seconds), jid))


def test_orphaned_running_job_is_reclaimed_by_lease(db_fresh):
    db = db_fresh
    ws = db.default_workspace()
    dead = db.create_job(ws, {"filename": "dead.pdf"})
    live = db.create_job(ws, {"filename": "live.pdf"})
    db.update_job(dead, status="running")
    db.update_job(live, status="running")  # fresh heartbeat
    _age_job(db, dead, 200)                 # its worker died ~200s ago

    n = db.reclaim_orphaned_jobs(lease_seconds=90)
    assert n == 1
    assert db.get_job(dead)["status"] == "queued"   # back in the queue → will resume
    assert db.get_job(live)["status"] == "running"  # actively heartbeating → untouched


def test_touch_job_keeps_the_lease_alive(db_fresh):
    db = db_fresh
    ws = db.default_workspace()
    jid = db.create_job(ws, {"filename": "busy.pdf"})
    db.update_job(jid, status="running")
    _age_job(db, jid, 200)
    db.touch_job(jid)  # the worker's heartbeat fires

    assert db.reclaim_orphaned_jobs(lease_seconds=90) == 0
    assert db.get_job(jid)["status"] == "running"


def test_reclaimed_job_keeps_page_checkpoints_for_resume(db_fresh):
    db = db_fresh
    ws = db.default_workspace()
    jid = db.create_job(ws, {"filename": "book.pdf"})
    db.update_job(jid, status="running")
    db.save_page_result(jid, 1, "# Page 1\n\nbody", [], 0.9)
    db.save_page_result(jid, 2, "# Page 2\n\nbody", [], 0.9)
    _age_job(db, jid, 200)

    assert db.reclaim_orphaned_jobs(lease_seconds=90) == 1
    assert db.get_job(jid)["status"] == "queued"
    # checkpoints survive → the next worker pass resumes from page 3, not page 1
    assert set(db.get_page_results(jid).keys()) == {1, 2}
