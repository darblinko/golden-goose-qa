"""Trace subgraph expansion and response mapping against an in-memory graph.

The fake answers the three fixed trace query shapes (anchor lookup by
whitelisted label, incident edges of a node set, edges among a node set) from
a small node and relationship list, so caps, ordering and provenance mapping
are exercised as graph behaviour rather than as a call script. Element ids are
opaque strings unrelated to the keys, so the mapping must read keys from the
whitelisted key property."""

import datetime
from typing import cast

import pytest
from gg_ingestion.extract.model import METHOD_CONFIDENCE, NODE_KEY_PROPERTY
from goldengoose_api import graph_trace
from goldengoose_api.graph_trace import Anchor, parse_anchor, trace_subgraph
from neo4j import AsyncDriver


class FakeGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, tuple[str, dict]] = {}
        self.rels: list[tuple[str, str, str, dict]] = []
        self.calls: list[tuple[str, dict | None]] = []

    def node(self, label: str, key: str, **properties) -> str:
        element_id = f"4:fake:{len(self.nodes)}"
        self.nodes[element_id] = (label, {NODE_KEY_PROPERTY[label]: key, **properties})
        return element_id

    def link(
        self,
        start: str,
        end: str,
        rel_type: str = "REFERENCES",
        method: str = "form_field",
        locator: str = "Source",
    ) -> None:
        start_label, start_props = self.nodes[start]
        self.rels.append(
            (
                start,
                end,
                rel_type,
                {
                    "method": method,
                    "locator": locator,
                    "source_doc_key": start_props[NODE_KEY_PROPERTY[start_label]],
                    "confidence": METHOD_CONFIDENCE[method],
                },
            )
        )

    def _degree(self, element_id: str) -> int:
        return sum((s == element_id) + (e == element_id) for s, e, _t, _p in self.rels)

    def _node_row(self, element_id: str) -> dict:
        label, properties = self.nodes[element_id]
        return {
            "element_id": element_id,
            "labels": [label],
            "properties": dict(properties),
            "degree": self._degree(element_id),
        }

    async def run_read(self, driver, query, parameters=None):
        self.calls.append((query, parameters))
        params = parameters or {}
        for label, key_property in NODE_KEY_PROPERTY.items():
            if query == graph_trace.anchor_query(label):
                return [
                    self._node_row(element_id)
                    for element_id, (node_label, props) in self.nodes.items()
                    if node_label == label and props[key_property] == params["key"]
                ]
        ids = set(params["element_ids"])
        if query == graph_trace.NEIGHBOURS_QUERY:
            rows = []
            for start, end, _type, props in self.rels:
                for origin, other in ((start, end), (end, start)):
                    if origin in ids:
                        row = self._node_row(other)
                        rows.append({**row, "from_id": origin, "confidence": props["confidence"]})
            return rows
        if query == graph_trace.EDGES_QUERY:
            return [
                {"start_id": s, "end_id": e, "type": t, "properties": dict(p)}
                for s, e, t, p in self.rels
                if s in ids and e in ids
            ]
        raise AssertionError(f"unexpected query: {query}")


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(graph_trace, "run_read", fake.run_read)
    return fake


async def _trace(anchor: str, hops: int = 2) -> dict:
    result = await trace_subgraph(cast(AsyncDriver, None), parse_anchor(anchor), hops)
    assert result is not None
    return result


def _node(result: dict, node_id: str) -> dict:
    return next(node for node in result["nodes"] if node["id"] == node_id)


def _keys_at_hop(result: dict, hop: int) -> list[str]:
    return [node["key"] for node in result["nodes"] if node["hop"] == hop]


class TestParseAnchor:
    def test_bare_key_means_document(self):
        assert parse_anchor("CAPA-2025-014") == Anchor(label="Document", key="CAPA-2025-014")

    def test_labelled_anchor(self):
        assert parse_anchor("Requirement:REQ-001") == Anchor(label="Requirement", key="REQ-001")
        assert parse_anchor("Person:Dana Whitfield") == Anchor(label="Person", key="Dana Whitfield")

    def test_key_may_contain_colons(self):
        assert parse_anchor("DocumentRevision:SOP-004:B") == Anchor(
            label="DocumentRevision", key="SOP-004:B"
        )
        assert parse_anchor("DFMEA-001:3") == Anchor(label="Document", key="DFMEA-001:3")

    @pytest.mark.parametrize("raw", ["Evil:x", "document:CAPA-1", "Node:1"])
    def test_unknown_label_rejected(self, raw):
        with pytest.raises(ValueError, match="unknown label"):
            parse_anchor(raw)

    @pytest.mark.parametrize(
        "raw",
        ["", "Document:", "CAPA;DROP", "Document:a}) DETACH DELETE n //", "x" * 81, "CAPA\n1"],
    )
    def test_invalid_key_rejected(self, raw):
        with pytest.raises(ValueError, match="anchor key"):
            parse_anchor(raw)

    def test_eighty_character_key_accepted(self):
        assert parse_anchor("k" * 80).key == "k" * 80

    def test_node_id_is_label_and_key(self):
        assert parse_anchor("CAPA-2025-014").node_id == "Document:CAPA-2025-014"


class TestAnchorQuery:
    def test_interpolates_only_whitelisted_label_and_key_property(self):
        for label, key_property in NODE_KEY_PROPERTY.items():
            query = graph_trace.anchor_query(label)
            assert f"(n:{label} {{{key_property}: $key}})" in query

    def test_unknown_label_refused(self):
        with pytest.raises(ValueError):
            graph_trace.anchor_query("Evil")


class TestExpansion:
    async def test_missing_anchor_returns_none(self, graph):
        result = await trace_subgraph(cast(AsyncDriver, None), parse_anchor("CAPA-404"), 2)
        assert result is None
        assert len(graph.calls) == 1

    async def test_bare_key_anchor_resolves_document(self, graph):
        graph.node("Document", "CAPA-2025-014", doc_type="capa")
        graph.node("Requirement", "CAPA-2025-014")
        result = await _trace("CAPA-2025-014")
        assert result["anchor"] == "Document:CAPA-2025-014"
        assert result["nodes"][0]["label"] == "Document"
        assert graph.calls[0][0] == graph_trace.anchor_query("Document")
        assert graph.calls[0][1] == {"key": "CAPA-2025-014"}

    async def test_hop1_ordered_by_confidence_then_key(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        for key, method in [
            ("A-low", "inline_regex"),
            ("Z-top", "trace_matrix"),
            ("B-mid", "form_field"),
            ("A-mid", "form_field"),
        ]:
            graph.link(anchor, graph.node("Document", key, doc_type="sop"), method=method)
        result = await _trace("CAPA-1", hops=1)
        assert _keys_at_hop(result, 1) == ["Z-top", "A-mid", "B-mid", "A-low"]
        assert result["truncated"] is False

    async def test_neighbour_ranked_by_its_best_edge(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        twice = graph.node("Document", "SOP-9", doc_type="sop")
        graph.link(anchor, twice, method="inline_regex")
        graph.link(twice, anchor, rel_type="REFERENCES", method="form_field")
        graph.link(
            anchor, graph.node("Document", "SOP-1", doc_type="sop"), method="references_section"
        )
        result = await _trace("CAPA-1", hops=1)
        assert _keys_at_hop(result, 1) == ["SOP-9", "SOP-1"]
        assert len(result["edges"]) == 3

    async def test_hop1_capped_at_forty(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        for index in range(45):
            graph.link(anchor, graph.node("Document", f"SOP-{index:03d}", doc_type="sop"))
        result = await _trace("CAPA-1", hops=1)
        assert _keys_at_hop(result, 1) == [f"SOP-{index:03d}" for index in range(40)]
        assert result["truncated"] is True
        anchor_node = _node(result, "Document:CAPA-1")
        assert anchor_node["degree"] == 45
        assert anchor_node["hidden_links"] == 5

    async def test_hops_one_skips_second_hop(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        ncr = graph.node("Document", "NCR-1", doc_type="ncr")
        graph.link(anchor, ncr, rel_type="SOURCED_FROM")
        graph.link(ncr, graph.node("Supplier", "SUP-1"), rel_type="FROM_SUPPLIER")
        result = await _trace("CAPA-1", hops=1)
        assert [node["key"] for node in result["nodes"]] == ["CAPA-1", "NCR-1"]
        assert _node(result, "Document:NCR-1")["hidden_links"] == 1
        assert result["truncated"] is False
        assert len(graph.calls) == 3

    async def test_hop2_per_node_cap_and_order(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        sop = graph.node("Document", "SOP-1", doc_type="sop")
        graph.link(anchor, sop)
        for index in range(10):
            method = "trace_matrix" if index == 9 else "inline_regex"
            graph.link(graph.node("Person", f"Person {index}"), sop, "TRAINED_ON", method)
        result = await _trace("CAPA-1")
        assert _keys_at_hop(result, 2) == ["Person 9", *[f"Person {i}" for i in range(7)]]
        assert result["truncated"] is True
        assert _node(result, "Document:SOP-1")["hidden_links"] == 2

    async def test_hop2_skips_nodes_already_selected_without_truncating(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        first = graph.node("Document", "NCR-1", doc_type="ncr")
        second = graph.node("Document", "NCR-2", doc_type="ncr")
        shared = graph.node("Supplier", "SUP-1")
        graph.link(anchor, first, "SOURCED_FROM")
        graph.link(anchor, second, "SOURCED_FROM")
        graph.link(first, second, "REFERENCES", "inline_regex")
        graph.link(first, shared, "FROM_SUPPLIER")
        graph.link(second, shared, "FROM_SUPPLIER")
        result = await _trace("CAPA-1")
        assert [node["key"] for node in result["nodes"]] == ["CAPA-1", "NCR-1", "NCR-2", "SUP-1"]
        assert [node["hop"] for node in result["nodes"]] == [0, 1, 1, 2]
        assert result["truncated"] is False

    async def test_cross_links_among_selected_nodes_returned(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        first = graph.node("Document", "NCR-1", doc_type="ncr")
        second = graph.node("Document", "NCR-2", doc_type="ncr")
        sup_a = graph.node("Supplier", "SUP-A")
        sup_b = graph.node("Supplier", "SUP-B")
        graph.link(anchor, first, "SOURCED_FROM")
        graph.link(anchor, second, "SOURCED_FROM")
        graph.link(first, second, "REFERENCES", "inline_regex")
        graph.link(first, sup_a, "FROM_SUPPLIER")
        graph.link(second, sup_b, "FROM_SUPPLIER")
        graph.link(sup_a, sup_b, "REFERENCES", "inline_regex")
        result = await _trace("CAPA-1")
        edge_ids = {edge["id"] for edge in result["edges"]}
        assert "Document:NCR-1|REFERENCES|Document:NCR-2" in edge_ids
        assert "Supplier:SUP-A|REFERENCES|Supplier:SUP-B" in edge_ids
        assert len(edge_ids) == 6
        assert all(node["hidden_links"] == 0 for node in result["nodes"])

    async def test_edge_cap_keeps_anchor_links_then_selection_links(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        for hop1_index in range(40):
            hop1 = graph.node("Document", f"SOP-{hop1_index:02d}", doc_type="sop")
            graph.link(anchor, hop1, method="inline_regex")
            for hop2_index in range(8):
                person = graph.node("Person", f"P{hop1_index:02d}-{hop2_index}")
                graph.link(person, hop1, "TRAINED_ON", "training_grid")
        result = await _trace("CAPA-1")
        assert len(result["nodes"]) == 1 + 40 + 320
        assert len(result["edges"]) == 150
        assert result["truncated"] is True
        anchor_edges = [e for e in result["edges"] if e["source"] == "Document:CAPA-1"]
        assert len(anchor_edges) == 40
        assert result["edges"][:40] == anchor_edges
        assert _node(result, "Document:CAPA-1")["hidden_links"] == 0

    async def test_edges_follow_stored_direction(self, graph):
        anchor = graph.node("Requirement", "REQ-001", text="Pace at 60 bpm.")
        output = graph.node("DesignOutput", "DO-003")
        graph.link(output, anchor, "SATISFIES", "trace_matrix", "row 3")
        result = await _trace("Requirement:REQ-001")
        assert result["edges"] == [
            {
                "id": "DesignOutput:DO-003|SATISFIES|Requirement:REQ-001",
                "source": "DesignOutput:DO-003",
                "target": "Requirement:REQ-001",
                "type": "SATISFIES",
                "method": "trace_matrix",
                "locator": "row 3",
                "source_doc_key": "DO-003",
                "confidence": 1.0,
                "inferred": False,
            }
        ]


class TestMapping:
    @pytest.mark.parametrize(
        ("method", "inferred"),
        [
            (method, method in ("references_section", "inline_regex"))
            for method in METHOD_CONFIDENCE
        ],
    )
    async def test_inferred_flag_from_method(self, graph, method, inferred):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        graph.link(anchor, graph.node("Document", "SOP-1", doc_type="sop"), method=method)
        result = await _trace("CAPA-1", hops=1)
        assert result["edges"][0]["inferred"] is inferred
        assert result["edges"][0]["method"] == method

    def test_text_mined_methods_are_known_methods(self):
        assert graph_trace.TEXT_MINED_METHODS.issubset(METHOD_CONFIDENCE)

    async def test_kind_mapping(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="CAPA")
        for label, key in [
            ("DocumentRevision", "CAPA-1:B"),
            ("Requirement", "REQ-001"),
            ("DesignOutput", "DO-001"),
            ("Supplier", "SUP-001"),
            ("Person", "Dana Whitfield"),
            ("FmeaRow", "DFMEA-001:3"),
        ]:
            graph.link(anchor, graph.node(label, key))
        graph.link(anchor, graph.node("Document", "UNTYPED-1"))
        result = await _trace("CAPA-1", hops=1)
        kinds = {node["label"] + ":" + node["key"]: node["kind"] for node in result["nodes"]}
        assert kinds == {
            "Document:CAPA-1": "capa",
            "DocumentRevision:CAPA-1:B": "revision",
            "Requirement:REQ-001": "requirement",
            "DesignOutput:DO-001": "design_output",
            "Supplier:SUP-001": "supplier",
            "Person:Dana Whitfield": "person",
            "FmeaRow:DFMEA-001:3": "fmea_row",
            "Document:UNTYPED-1": "document",
        }

    async def test_properties_exclude_key_title_body_and_non_scalars(self, graph):
        graph.node(
            "Document",
            "CAPA-1",
            doc_type="capa",
            title="Seal failure CAPA",
            revision="B",
            effective_from=datetime.date(2025, 3, 1),
            open=True,
            severity=3,
            body="full narrative text",
            content="more text",
            tags=["a", "b"],
        )
        result = await _trace("CAPA-1")
        anchor = result["nodes"][0]
        assert anchor["title"] == "Seal failure CAPA"
        assert anchor["properties"] == {
            "doc_type": "capa",
            "effective_from": "2025-03-01",
            "open": True,
            "revision": "B",
            "severity": 3,
        }

    async def test_title_null_when_absent(self, graph):
        graph.node("Supplier", "SUP-001", name="Acme Polymers")
        result = await _trace("Supplier:SUP-001")
        anchor = result["nodes"][0]
        assert anchor["title"] is None
        assert anchor["properties"] == {"name": "Acme Polymers"}

    async def test_hidden_links_count_unselected_neighbours(self, graph):
        anchor = graph.node("Document", "CAPA-1", doc_type="capa")
        sop = graph.node("Document", "SOP-1", doc_type="sop")
        person = graph.node("Person", "Dana Whitfield")
        graph.link(anchor, sop)
        graph.link(person, sop, "TRAINED_ON", "training_grid")
        for index in range(3):
            graph.link(person, graph.node("Document", f"WI-{index}", doc_type="wi"), "TRAINED_ON")
        result = await _trace("CAPA-1")
        dana = _node(result, "Person:Dana Whitfield")
        assert dana["hop"] == 2
        assert dana["degree"] == 4
        assert dana["hidden_links"] == 3
