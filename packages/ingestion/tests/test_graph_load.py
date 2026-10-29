import pytest
from gg_ingestion.extract.graph_load import (
    edge_conflicts,
    edge_properties,
    edge_query,
    node_query,
)
from gg_ingestion.extract.model import Edge, Provenance


def _edge(method: str, *, protocol_id: str, doc_key: str) -> Edge:
    return Edge(
        rel_type="VERIFIES",
        start_label="Document",
        start_key="VTR-001",
        end_label="Requirement",
        end_key="REQ-001",
        provenance=Provenance(doc_key=doc_key, method=method, locator="row 4"),
        properties={"protocol_id": protocol_id},
    )


def test_node_query_uses_label_key_property():
    query = node_query("Document")
    assert "MERGE (n:Document {doc_key: row.key})" in query
    assert node_query("FmeaRow").count("{key: row.key}") == 1


def test_node_query_rejects_unknown_label():
    with pytest.raises(ValueError, match="unknown node label"):
        node_query("Document) DETACH DELETE n //")


def test_edge_query_merges_both_endpoints():
    query = edge_query("VERIFIES", "Document", "Requirement")
    assert "MERGE (a:Document {doc_key: row.start})" in query
    assert "MERGE (b:Requirement {req_id: row.end})" in query
    assert "MERGE (a)-[r:VERIFIES]->(b)" in query
    # A strictly-higher confidence overwrites; an equal-confidence tie does NOT
    # (first-writer-wins), so ties are deterministic, not last-writer-wins.
    assert "coalesce(r.confidence, -1.0) < row.properties.confidence" in query
    assert "<=" not in query


def test_edge_query_rejects_unknown_rel_and_labels():
    with pytest.raises(ValueError, match="unknown relationship type"):
        edge_query("OWNS", "Document", "Requirement")
    with pytest.raises(ValueError, match="unknown edge endpoint label"):
        edge_query("VERIFIES", "Document", "Widget")


def test_edge_properties_flatten_provenance_and_drop_none():
    edge = Edge(
        rel_type="VERIFIES",
        start_label="Document",
        start_key="VTR-001",
        end_label="Requirement",
        end_key="REQ-001",
        provenance=Provenance(doc_key="TM-100", method="trace_matrix", locator="row 4"),
        properties={"protocol_id": "VTP-001", "result": None},
    )
    properties = edge_properties(edge)
    assert properties["source_doc_key"] == "TM-100"
    assert properties["method"] == "trace_matrix"
    assert properties["confidence"] == 1.0
    assert properties["protocol_id"] == "VTP-001"
    assert "result" not in properties


def test_edge_conflicts_flags_equal_confidence_disagreement():
    # trace_matrix and fmea_sheet are both confidence 1.0 but assert a different
    # protocol_id for the same edge; the loader keeps the first, so the conflict
    # is surfaced rather than silently overwritten.
    edges = [
        _edge("trace_matrix", protocol_id="VTP-001", doc_key="TM-100"),
        _edge("fmea_sheet", protocol_id="VTP-002", doc_key="DFMEA-9"),
    ]
    conflicts = edge_conflicts(edges)
    assert len(conflicts) == 1
    assert "VTR-001 -[VERIFIES]-> REQ-001" in conflicts[0]
    assert "TM-100" in conflicts[0] and "DFMEA-9" in conflicts[0]
    assert "kept TM-100" in conflicts[0]  # deterministic first-writer


def test_edge_conflicts_ignores_pure_corroboration():
    # Same assertion from two sources at equal confidence is not a conflict.
    edges = [
        _edge("trace_matrix", protocol_id="VTP-001", doc_key="TM-100"),
        _edge("fmea_sheet", protocol_id="VTP-001", doc_key="DFMEA-9"),
    ]
    assert edge_conflicts(edges) == []


def test_edge_conflicts_ignores_confidence_ranked_disagreement():
    # A lower-confidence disagreement loses cleanly (strict overwrite), so it is
    # adjudicated, not a tie.
    edges = [
        _edge("trace_matrix", protocol_id="VTP-001", doc_key="TM-100"),  # 1.0 wins
        _edge("form_field", protocol_id="VTP-002", doc_key="VTR-002"),  # 0.95 loses
    ]
    assert edge_conflicts(edges) == []


def test_edge_conflicts_empty_for_unique_edges():
    edges = [_edge("trace_matrix", protocol_id="VTP-001", doc_key="TM-100")]
    assert edge_conflicts(edges) == []
