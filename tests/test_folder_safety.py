"""Folders must not orphan documents: deleting a non-empty folder (or a parent whose
subfolder holds documents) is refused; orphaned docs are listed as 'unfiled' and can be
moved (drag-and-drop) back into a folder."""
import pytest

pytestmark = pytest.mark.integration


def test_cannot_delete_folder_containing_documents(api_client):
    c = api_client
    parent = c.post("/v1/folders", json={"name": "Parent"}).json()["folder_id"]
    child = c.post("/v1/folders", json={"name": "Child", "parent_id": parent}).json()["folder_id"]
    did = c.post("/v1/documents/markdown",
                 json={"title": "doc", "content": "# D\n\nbody.\n", "folder_id": child}).json()["document_id"]

    # deleting the child (holds the doc) is refused with a clear message
    r = c.delete(f"/v1/folders/{child}")
    assert r.status_code == 409
    assert "not empty" in r.json()["detail"].lower()
    # deleting the PARENT is also refused (a subfolder holds the doc)
    assert c.delete(f"/v1/folders/{parent}").status_code == 409
    # the document is still attached (not orphaned)
    assert c.get(f"/v1/documents/{did}").json()["folder_id"] == child


def test_unfiled_listing_and_drag_move(api_client):
    c = api_client
    box = c.post("/v1/folders", json={"name": "Box"}).json()["folder_id"]
    did = c.post("/v1/documents/markdown",
                 json={"title": "orphan", "content": "# O\n\nbody.\n"}).json()["document_id"]
    # no folder → appears in unfiled
    assert any(d["id"] == did for d in c.get("/v1/unfiled").json()["documents"])
    # drag-move into a folder (PATCH folder_id) → no longer unfiled
    assert c.patch(f"/v1/documents/{did}", json={"folder_id": box}).status_code == 200
    assert c.get(f"/v1/documents/{did}").json()["folder_id"] == box
    assert all(d["id"] != did for d in c.get("/v1/unfiled").json()["documents"])
    # the folder now holds it → deletion refused
    assert c.delete(f"/v1/folders/{box}").status_code == 409


def test_empty_folder_can_be_deleted(api_client):
    c = api_client
    empty = c.post("/v1/folders", json={"name": "Empty"}).json()["folder_id"]
    assert c.delete(f"/v1/folders/{empty}").status_code == 200
