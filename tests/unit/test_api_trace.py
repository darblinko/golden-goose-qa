"""Trace route: role gate, anchor validation, response shape, and the Cypher
boundary.

Exercised without Neo4j: run_read in the trace module is replaced with a
scripted stub that returns canned rows in call order and records every
(query, parameters) pair, so the tests can assert that request text reaches
the graph only as a parameter and that rejected requests run no query."""

import re

import pytest
from fastapi.testclient import TestClient
from gg_ingestion.extract.model import NODE_KEY_PROPERTY
from goldengoose_api import graph_trace
from goldengoose_api.auth import mint_dev_token
from goldengoose_api.main import create_app

_ANCHOR_ROW = {
    "element_id": "4:a:0",
    "properties": {
        "doc_key": "CAPA-2025-014",
        "doc_type": "capa",
        "title": "Seal failure CAPA",
        "revision": "B",
        "effective_from": "2025-03-01",
    },
    "degree": 2,
}
_HOP1_ROWS = [
    {
        "from_id": "4:a:0",
        "confidence": 0.95,
        "element_id": "4:a:1",
        "labels": ["Document"],
        "properties": {"doc_key": "NCR-2025-001", "doc_type": "ncr"},
        "degree": 1,
    }
]
_EDGE_ROWS = [
    {
        "start_id": "4:a:0",
        "end_id": "4:a:1",
        "type": "SOURCED_FROM",
        "properties": {
            "method": "form_field",
            "locator": "Source",
            "source_doc_key": "CAPA-2025-014",
            "confidence": 0.95,
        },
    }
]


@pytest.fixture()
def harness(monkeypatch):
    app = create_app()
    app.state.graph_driver = None
    settings = app.state.settings
    responses: list[list[dict]] = []
    calls: list[tuple[str, dict | None]] = []

    async def scripted_run_read(driver, query, parameters=None):
        calls.append((query, parameters))
        return responses.pop(0) if responses else []

    monkeypatch.setattr(graph_trace, "run_read", scripted_run_read)

    def auth(role="qa_user"):
        token = mint_dev_token(settings, email=f"{role}@example.com", role=role)
        return {"Authorization": f"Bearer {token}"}

    return TestClient(app), responses, calls, auth


def test_trace_returns_contract_shape(harness):
    client, responses, calls, auth = harness
    responses.extend([[_ANCHOR_ROW], _HOP1_ROWS, [], _EDGE_ROWS])

    response = client.get("/graph/trace?anchor=CAPA-2025-014", headers=auth())

    assert response.status_code == 200
    assert response.json() == {
        "anchor": "Document:CAPA-2025-014",
        "hops": 2,
        "nodes": [
            {
                "id": "Document:CAPA-2025-014",
                "label": "Document",
                "key": "CAPA-2025-014",
                "title": "Seal failure CAPA",
                "kind": "capa",
                "hop": 0,
                "degree": 2,
                "hidden_links": 1,
                "properties": {"doc_type": "capa", "revision": "B", "effective_from": "2025-03-01"},
            },
            {
                "id": "Document:NCR-2025-001",
                "label": "Document",
                "key": "NCR-2025-001",
                "title": None,
                "kind": "ncr",
                "hop": 1,
                "degree": 1,
                "hidden_links": 0,
                "properties": {"doc_type": "ncr"},
            },
        ],
        "edges": [
            {
                "id": "Document:CAPA-2025-014|SOURCED_FROM|Document:NCR-2025-001",
                "source": "Document:CAPA-2025-014",
                "target": "Document:NCR-2025-001",
                "type": "SOURCED_FROM",
                "method": "form_field",
                "locator": "Source",
                "source_doc_key": "CAPA-2025-014",
                "confidence": 0.95,
                "inferred": False,
            }
        ],
        "truncated": False,
    }
    assert len(calls) == 4


def test_admin_allowed(harness):
    client, responses, _calls, auth = harness
    responses.extend([[_ANCHOR_ROW], [], []])
    response = client.get("/graph/trace?anchor=CAPA-2025-014&hops=1", headers=auth("admin"))
    assert response.status_code == 200
    assert response.json()["hops"] == 1


def test_unknown_anchor_returns_404(harness):
    client, _responses, calls, auth = harness
    response = client.get("/graph/trace?anchor=CAPA-2099-999", headers=auth())
    assert response.status_code == 404
    assert response.json() == {"detail": "anchor not found"}
    assert len(calls) == 1


@pytest.mark.parametrize(
    "query",
    [
        "anchor=CAPA%3BDROP",
        "anchor=" + "x" * 81,
        "anchor=Document%3A",
        "anchor=",
        "",
        "anchor=Evil%3ACAPA-2025-014",
        "anchor=document%3ACAPA-2025-014",
        "anchor=CAPA-2025-014&hops=3",
        "anchor=CAPA-2025-014&hops=0",
        "anchor=CAPA-2025-014&hops=two",
    ],
)
def test_invalid_request_returns_422_without_querying(harness, query):
    client, _responses, calls, auth = harness
    response = client.get(f"/graph/trace?{query}", headers=auth())
    assert response.status_code == 422
    assert calls == []


def test_auditor_readonly_forbidden(harness):
    client, _responses, calls, auth = harness
    response = client.get("/graph/trace?anchor=CAPA-2025-014", headers=auth("auditor_readonly"))
    assert response.status_code == 403
    assert calls == []


def test_missing_token_is_unauthorized(harness):
    client, _responses, calls, _auth = harness
    assert client.get("/graph/trace?anchor=CAPA-2025-014").status_code == 401
    assert calls == []


def test_request_text_reaches_cypher_only_as_parameter(harness):
    client, responses, calls, auth = harness
    supplier_row = {
        "element_id": "4:s:0",
        "properties": {"supplier_id": "SUP-001", "name": "Acme"},
        "degree": 0,
    }
    responses.extend([[supplier_row], [], []])

    response = client.get(
        "/graph/trace?anchor=Supplier%3ASUP-001&hops=1&label=Evil&key_property=evil_prop",
        headers=auth(),
    )

    assert response.status_code == 200
    assert calls[0] == (graph_trace.anchor_query("Supplier"), {"key": "SUP-001"})
    assert "(n:Supplier {supplier_id: $key})" in calls[0][0]
    assert calls[1][0] == graph_trace.NEIGHBOURS_QUERY
    assert calls[2][0] == graph_trace.EDGES_QUERY
    for query, _parameters in calls:
        assert "SUP-001" not in query
        assert "Evil" not in query
        assert "evil_prop" not in query
        interpolated_labels = set(re.findall(r"\(\w+:(\w+)", query))
        assert interpolated_labels <= NODE_KEY_PROPERTY.keys()
