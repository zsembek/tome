"""Per-stage ingest timing metrics: recorded into the job payload and exposed via
list_jobs and the /v1/stats Health aggregate."""
import pytest

pytestmark = pytest.mark.integration


def test_ingest_records_stage_timings(api_client, ingest):
    job = ingest("metrics.md", "# Title\n\nA reasonably long body about pumps, seals and maintenance.")
    from tome.db import DB
    db = DB()
    ws = db.default_workspace()
    rows = db.list_jobs(ws, limit=10)
    row = next(r for r in rows if r["id"] == job["id"])
    t = row["timings_ms"]
    assert isinstance(t, dict)
    for stage in ("extract", "structure", "persist"):
        assert stage in t and isinstance(t[stage], int) and t[stage] >= 0


def test_stats_exposes_avg_stage_ms(api_client, ingest):
    ingest("m2.md", "# Doc\n\nBody text long enough to be a real section about equipment.")
    s = api_client.get("/v1/stats").json()
    assert "avg_stage_ms" in s
    assert isinstance(s["avg_stage_ms"], dict) and "extract" in s["avg_stage_ms"]
    assert s["avg_stage_ms_sampled"] >= 1
