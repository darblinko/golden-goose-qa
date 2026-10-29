"""GraphWalker tests with a scripted run_read.

The stub returns canned record lists in call order and captures every
(query, params) pair, verifying values travel as parameters — never
interpolated — and that rows compose into the uniform edge shape with
provenance doc keys collected.
"""

from typing import cast

import gg_retrieval.tools.graph_walk as graph_walk_mod
import pytest
from gg_common.settings import AppSettings, ToolSettings
from gg_retrieval.tools.graph_walk import EDGE_COLUMNS, GraphWalker
from neo4j import AsyncDriver


@pytest.fixture
def make_walker(monkeypatch):
    def factory(responses, **tool_settings):
        calls = []
        queue = list(responses)

        async def scripted_run_read(driver, query, parameters=None):
            calls.append((query, parameters))
            return queue.pop(0) if queue else []

        monkeypatch.setattr(graph_walk_mod, "run_read", scripted_run_read)
        settings = AppSettings(tools=ToolSettings(**tool_settings))
        return GraphWalker(driver=cast(AsyncDriver, None), settings=settings), calls

    return factory


class TestRequirementTrace:
    async def test_composes_anchor_and_edge_rows(self, make_walker):
        walker, calls = make_walker(
            [
                [
                    {
                        "req_id": "REQ-001",
                        "category": "Performance",
                        "text": "Pace at 60 bpm.",
                        "source_doc": "TM-100",
                        "locator": "row 3",
                    }
                ],
                [{"from_key": "DO-003", "source_doc": "TM-100"}],
                [
                    {
                        "from_key": "VTR-001",
                        "protocol_id": "VTP-001",
                        "result": "Pass",
                        "source_doc": "TM-100",
                    }
                ],
            ]
        )
        result = await walker.requirement_trace("REQ-001")

        assert result.columns == EDGE_COLUMNS
        assert [row["relation"] for row in result.rows] == [
            "REQUIREMENT",
            "SATISFIES",
            "VERIFIES",
        ]
        # The anchor row cites the trace matrix it was defined in, with its row.
        anchor = result.rows[0]
        assert anchor["source_doc"] == "TM-100"
        assert "defined at row 3" in anchor["detail"]
        verifies = result.rows[2]
        assert verifies["from_key"] == "VTR-001"
        assert verifies["detail"] == "protocol VTP-001, result Pass"
        assert result.source_doc_keys == ("TM-100",)
        assert all(parameters == {"req_id": "REQ-001"} for _, parameters in calls)

    async def test_missing_requirement_is_empty_not_an_error(self, make_walker):
        walker, calls = make_walker([[]])
        result = await walker.requirement_trace("REQ-999")
        assert result.is_empty
        assert "not in graph" in result.title
        assert len(calls) == 1  # no edge queries after a missing anchor


class TestListQueries:
    async def test_unverified_requirements_shape(self, make_walker):
        walker, _ = make_walker(
            [
                [
                    {
                        "req_id": "REQ-017",
                        "category": "Safety",
                        "requirement_text": "...",
                        "source_doc": "TM-100",
                        "locator": "row 17",
                    }
                ]
            ]
        )
        result = await walker.unverified_requirements()
        assert result.columns == ("req_id", "category", "requirement_text", "source_doc", "locator")
        assert result.rows[0]["req_id"] == "REQ-017"
        # An unverified requirement is a compliance finding: it must cite the
        # exact document and row it was read from, not just list a bare id.
        assert result.rows[0]["source_doc"] == "TM-100"
        assert result.rows[0]["locator"] == "row 17"
        assert result.source_doc_keys == ("TM-100",)

    async def test_fmea_mismatches_cite_their_sheets(self, make_walker):
        walker, _ = make_walker(
            [
                [
                    {
                        "doc_key": "DFMEA-100",
                        "row_id": 3,
                        "item": "Battery",
                        "failure_mode": "Depletion",
                        "severity": 9,
                        "occurrence": 2,
                        "detection": 3,
                        "ap_recorded": "M",
                        "ap_computed": "H",
                    }
                ]
            ]
        )
        result = await walker.fmea_ap_mismatches()
        assert result.source_doc_keys == ("DFMEA-100",)
        assert result.rows[0]["ap_computed"] == "H"

    async def test_stale_references_compare_cited_and_current_revisions(self, make_walker):
        walker, calls = make_walker(
            [
                [
                    {
                        "doc_key": "SOP-016",
                        "referenced_doc": "WI-101",
                        "cited_revision": "A",
                        "current_revision": "B",
                        "locator": "References",
                        "source_doc": "SOP-016",
                    }
                ]
            ]
        )
        result = await walker.stale_references()
        assert result.rows[0]["cited_revision"] == "A"
        assert result.rows[0]["current_revision"] == "B"
        assert result.source_doc_keys == ("SOP-016",)
        assert "cited_revision <> t.revision" in calls[0][0]

    async def test_stale_training_lists_superseded_revisions(self, make_walker):
        walker, _ = make_walker(
            [
                [
                    {
                        "person": "Dana Ruiz",
                        "role": "Quality Engineer",
                        "doc_key": "SOP-004",
                        "trained_revision": "A",
                        "current_revision": "B",
                        "source_doc": "TRN-100",
                    }
                ]
            ]
        )
        result = await walker.stale_training()
        assert result.rows[0]["doc_key"] == "SOP-004"
        assert result.rows[0]["trained_revision"] == "A"
        assert result.source_doc_keys == ("TRN-100",)

    async def test_training_status_carries_current_revision(self, make_walker):
        walker, calls = make_walker(
            [
                # The document-existence check runs first; it must exist before
                # an empty training set means "nobody trained" rather than
                # "not in corpus."
                [{"doc_type": "wi", "title": "Assembly WI", "revision": "B"}],
                [
                    {
                        "person": "Dana Ruiz",
                        "role": "Quality Engineer",
                        "trained_revision": "A",
                        "trained_on": "2024-05-02",
                        "current_revision": "B",
                        "source_doc": "TRN-100",
                    }
                ],
            ]
        )
        result = await walker.training_status("SOP-004")
        assert not result.anchor_missing
        assert result.rows[0]["trained_revision"] == "A"
        assert result.rows[0]["current_revision"] == "B"
        assert calls[-1][1] == {"doc_key": "SOP-004"}

    async def test_training_status_missing_document_is_not_in_corpus(self, make_walker):
        """A compound key like WI-MFG-014 that is absent from the graph yields a
        flagged empty result — an honest 'not in corpus,' never a grounded
        empty training table."""
        walker, calls = make_walker([[]])  # document-existence check finds nothing
        result = await walker.training_status("WI-MFG-014")
        assert result.is_empty
        assert result.anchor_missing
        assert "not in graph" in result.title
        assert len(calls) == 1  # no training query after a missing document


class TestRecordThread:
    async def test_hop_bound_comes_from_settings(self, make_walker):
        # The record-existence check runs first, then the bounded thread query.
        walker, calls = make_walker(
            [[{"doc_type": "capa", "title": "CAPA", "revision": None}], []],
            graph_record_hops=2,
        )
        await walker.record_thread("CAPA-2025-007")
        query, parameters = calls[-1]
        assert "*1..2" in query
        assert parameters == {"doc_key": "CAPA-2025-007"}

    async def test_rows_capped_by_graph_row_limit(self, make_walker):
        records = [
            {
                "relation": "ESCALATED_TO",
                "from_key": f"NCR-{i:03d}",
                "to_key": "CAPA-2025-007",
                "source_doc": f"NCR-{i:03d}",
            }
            for i in range(5)
        ]
        walker, _ = make_walker(
            [[{"doc_type": "capa", "title": "CAPA", "revision": None}], records],
            graph_row_limit=2,
        )
        result = await walker.record_thread("CAPA-2025-007")
        assert result.truncated
        assert len(result.rows) == 2

    async def test_missing_record_is_not_in_corpus(self, make_walker):
        """A thread walk for a record absent from the graph (the CAPA-2025-014
        acceptance case before the corpus seeds it) is a flagged empty result,
        never a grounded empty thread."""
        walker, calls = make_walker([[]])  # existence check finds nothing
        result = await walker.record_thread("CAPA-2099-999")
        assert result.is_empty
        assert result.anchor_missing
        assert "not in graph" in result.title
        assert len(calls) == 1  # no thread query after a missing record


class TestSupplierProfile:
    async def test_anchor_row_then_audits_and_ncrs(self, make_walker):
        walker, _ = make_walker(
            [
                [
                    {
                        "name": "Velmed Polymers",
                        "commodity": "Molded components",
                        "approval_status": "Approved",
                        "last_audit": "2025-01-15",
                    }
                ],
                [{"doc_key": "ASR-003", "source_doc": "ASL-100"}],
                [{"doc_key": "NCR-2025-011", "source_doc": "NCR-2025-011"}],
            ]
        )
        result = await walker.supplier_profile("SUP-003")
        assert [row["relation"] for row in result.rows] == [
            "SUPPLIER",
            "AUDITS",
            "FROM_SUPPLIER",
        ]
        assert "Velmed Polymers" in result.rows[0]["detail"]
        assert result.source_doc_keys == ("ASL-100", "NCR-2025-011")
