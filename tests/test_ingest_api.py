"""S4: ingestion + folder-tree + atlas-tree API parity.

REST must support building a folder tree, attaching documents to folders, ingesting
ready Markdown (no file upload), and exposing the Atlas as a real nested structure."""
import pytest

pytestmark = pytest.mark.integration


def test_ingest_markdown_into_nested_folder(api_client):
    c = api_client
    r = c.post("/v1/documents/markdown", json={
        "title": "Pump NTs-100",
        "content": "# Pump NTs-100\n\nPressure 0.7 MPa, power 11 kW.\n\n## Operation\n\nCheck oil.\n",
        "folder_path": "Manuals/Pumps/Centrifugal",
    })
    assert r.status_code == 200, r.text
    did = r.json()["document_id"]
    # the nested folder tree was created
    tree = c.get("/v1/folders").json()["folders"]
    paths = {f["path"] for f in tree}
    assert any(p.endswith("centrifugal") for p in paths)
    # content preserved as Markdown
    content = c.get(f"/v1/documents/{did}/content").json()["markdown"]
    assert "0.7 MPa" in content and "11 kW" in content


def test_create_subfolder_by_parent_id(api_client):
    c = api_client
    root = c.post("/v1/folders", json={"name": "Vendors"}).json()
    assert root["folder_id"]
    child = c.post("/v1/folders", json={"name": "Acme", "parent_id": root["folder_id"]}).json()
    assert child["folder_id"] and child["folder_id"] != root["folder_id"]
    # child is nested under root
    kids = c.get(f"/v1/folders?lazy=true&parent_id={root['folder_id']}").json()["folders"]
    assert any(k["id"] == child["folder_id"] and k["name"] == "Acme" for k in kids)


def test_move_document_by_folder_id(api_client):
    c = api_client
    a = c.post("/v1/folders", json={"name": "A"}).json()["folder_id"]
    b = c.post("/v1/folders", json={"name": "B"}).json()["folder_id"]
    did = c.post("/v1/documents/markdown",
                 json={"title": "doc", "content": "# Doc\n\nbody.\n", "folder_id": a}).json()["document_id"]
    assert c.get(f"/v1/documents/{did}").json()["folder_id"] == a
    assert c.patch(f"/v1/documents/{did}", json={"folder_id": b}).status_code == 200
    assert c.get(f"/v1/documents/{did}").json()["folder_id"] == b


def test_atlas_tree_is_hierarchical_with_names(api_client):
    c = api_client
    c.post("/v1/documents/markdown",
           json={"title": "Centrifugal pump", "content": "# Pump\n\nbody.\n",
                 "folder_path": "Manuals/Pumps"})
    tree = c.get("/v1/atlas/tree").json()["tree"]
    # real structure: named folders, nested children, document titles — not a flat list
    assert tree and any(n["name"] == "Manuals" for n in tree)
    manuals = [n for n in tree if n["name"] == "Manuals"][0]
    assert "children" in manuals and manuals["children"]
    pumps = manuals["children"][0]
    assert pumps["name"] == "Pumps"
    assert any(d["title"] == "Centrifugal pump" for d in pumps.get("documents", []))
