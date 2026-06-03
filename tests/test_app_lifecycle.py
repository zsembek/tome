"""Sprint 0 debt: FastAPI lifespan (not deprecated on_event), clean pool shutdown,
and a correct root() that doesn't advertise an unmounted /ui."""
import os

import pytest


@pytest.mark.integration
def test_root_advertises_docs_not_unmounted_ui(api_client):
    body = api_client.get("/").json()
    assert body.get("docs") == "/docs"
    assert "ui" not in body, "gateway must not advertise an unmounted /ui path"


@pytest.mark.integration
def test_db_pool_closed_on_shutdown():
    if not os.environ.get("TOME_TEST_DSN"):
        pytest.skip("TOME_TEST_DSN is not set")
    import api.deps as deps
    import api.main as m
    from fastapi.testclient import TestClient
    with TestClient(m.app):
        assert deps.get_db() is not None        # opened on startup
    assert deps._db is None                      # lifespan shutdown closed + reset it
