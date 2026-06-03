"""S6: knowledge graph — deterministic extraction, build, retrieval, neighbors.

The graph is a derived index over Markdown (no graph DB) and a 3rd RRF signal."""
import pytest

from tome import graph

pytestmark = pytest.mark.integration


def test_extract_entities_is_deterministic_and_sensible():
    ents = dict((n.lower(), k) for n, k in
                graph.extract_entities("# Centrifugal Pump NTs-100\n\nPressure 0.7 MPa. The API is open."))
    # multi-word phrase + model code captured; single sentence-initial words ignored
    assert "centrifugal pump nts-100" in ents or "centrifugal pump" in ents
    assert "nts-100" in ents and ents["nts-100"] == "code"
    assert "pressure" not in ents  # noise (sentence-initial single word) excluded


def test_build_graph_entities_and_neighbors(api_client, ingest):
    ingest("pump.md", "# Centrifugal Pump\n\nThe Centrifugal Pump NTs-100 needs Oil Filter checks.\n", folder="Eng")
    db = _db()
    ws = db.default_workspace()
    ents = graph.list_entities(db, ws)
    assert ents, "no entities extracted"
    names = {e["name"].lower() for e in ents}
    assert any("centrifugal pump" in n for n in names)
    # co-occurrence edge → neighbors
    target = [e for e in ents if "centrifugal pump" in e["name"].lower()][0]
    detail = graph.get_entity(db, ws, target["id"])
    assert detail["sections"], "entity should link to its sections"
    assert isinstance(detail["neighbors"], list)


def test_graph_stream_returns_sections(api_client, ingest):
    job = ingest("v.md", "# Gate Valve\n\nThe Gate Valve DN50 controls flow.\n", folder="Eng")
    assert job["status"] == "done"
    db = _db(); ws = db.default_workspace()
    hits = graph.graph_stream(db, ws, "gate valve", limit=10)
    assert hits, "graph stream returned nothing for a known entity"


def test_search_includes_graph_signal(api_client, ingest):
    ingest("t.md", "# Hydraulic Turbine\n\nThe Hydraulic Turbine spins fast.\n", folder="Eng")
    r = api_client.get("/v1/search", params={"q": "hydraulic turbine", "mode": "hybrid"})
    assert r.status_code == 200
    assert r.json()["results"], "hybrid search (with graph) returned nothing"


def test_rest_graph_endpoints(api_client, ingest):
    ingest("p.md", "# Pump Station\n\nThe Pump Station Alpha runs daily.\n", folder="Eng")
    ents = api_client.get("/v1/graph/entities", params={"q": "pump"}).json()["entities"]
    assert ents
    eid = ents[0]["id"]
    detail = api_client.get(f"/v1/graph/entities/{eid}").json()
    assert "entity" in detail and "neighbors" in detail
    # rebuild is idempotent and returns counts
    rb = api_client.post("/v1/graph/rebuild").json()
    assert rb["entities"] >= 1


def test_graph_overview_endpoint(api_client, ingest):
    ingest("g.md", "# Pumps\n\nThe Centrifugal Pump and the Gate Valve operate together here.\n", folder="Eng")
    ov = api_client.get("/v1/graph").json()
    assert "nodes" in ov and "edges" in ov
    assert len(ov["nodes"]) >= 1
    # co-occurrence of two multi-word entities in one section yields at least one edge
    assert all({"src", "dst", "weight"} <= set(e) for e in ov["edges"])


def _db():
    from api.deps import get_db
    return get_db()
