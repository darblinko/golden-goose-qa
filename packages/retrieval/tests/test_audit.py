"""Audit workflow tests: catalogue consistency, runner behavior with stub
tools, and the advisory note's fallback to the deterministic summary."""

import inspect
from typing import cast

import pytest
from gg_common.providers.base import ChatMessage, LLMProvider
from gg_retrieval.audit import (
    AUDIT_CHECKS,
    AUDIT_COLLECTIONS,
    CHECKS_BY_ID,
    AuditReport,
    AuditReportRunner,
    advisory_note,
)
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.models import ToolResult
from gg_retrieval.tools.warehouse import SAVED_QUERIES, WarehouseTool

# The five defect patterns seeded by gg_synthdata.world; every one must have
# a gate in the catalogue so the readiness report reproduces the full set.
SEEDED_DEFECT_KINDS = frozenset(
    {
        "broken_trace_link",
        "ap_mismatch",
        "overdue_effectiveness_check",
        "complaint_without_risk_evaluation",
        "stale_sop_reference",
    }
)


def tool_result(rows, *, truncated=False) -> ToolResult:
    return ToolResult(
        tool="warehouse",
        title="stub",
        source="stub source",
        query="stub query",
        columns=tuple(rows[0]) if rows else (),
        rows=tuple(rows),
        truncated=truncated,
    )


class StubWarehouse:
    def __init__(self, rows_by_name=None, fail=()):
        self.rows_by_name = rows_by_name or {}
        self.fail = frozenset(fail)
        self.calls = []

    async def run_saved(self, name, params=None):
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError("warehouse unavailable")
        return tool_result(self.rows_by_name.get(name, []))


class StubGraph:
    def __init__(self, rows_by_method=None, fail=()):
        self.rows_by_method = rows_by_method or {}
        self.fail = frozenset(fail)
        self.calls = []

    def __getattr__(self, name):
        async def method():
            self.calls.append(name)
            if name in self.fail:
                raise RuntimeError("graph unavailable")
            return tool_result(self.rows_by_method.get(name, []))

        return method


def make_runner(warehouse=None, graph=None) -> AuditReportRunner:
    return AuditReportRunner(
        warehouse=cast(WarehouseTool, warehouse or StubWarehouse()),
        graph=cast(GraphWalker, graph or StubGraph()),
    )


class TestCatalogue:
    def test_check_ids_unique(self):
        ids = [check.check_id for check in AUDIT_CHECKS]
        assert len(ids) == len(set(ids))

    def test_warehouse_refs_are_parameterless_saved_queries(self):
        for check in AUDIT_CHECKS:
            if check.source == "warehouse":
                assert check.ref in SAVED_QUERIES, check.check_id
                assert SAVED_QUERIES[check.ref].params == (), check.check_id

    def test_graph_refs_are_parameterless_walker_methods(self):
        for check in AUDIT_CHECKS:
            if check.source == "graph":
                method = getattr(GraphWalker, check.ref, None)
                assert method is not None, check.check_id
                parameters = list(inspect.signature(method).parameters)
                assert parameters == ["self"], check.check_id

    def test_every_seeded_defect_kind_has_a_gate(self):
        covered = {check.defect_kind for check in AUDIT_CHECKS if check.defect_kind}
        assert covered == SEEDED_DEFECT_KINDS

    def test_collections_reference_known_checks_and_cover_all(self):
        referenced = set()
        for collection in AUDIT_COLLECTIONS:
            for check_id in collection.check_ids:
                assert check_id in CHECKS_BY_ID, collection.collection_id
                referenced.add(check_id)
        assert referenced == set(CHECKS_BY_ID)


class TestRunner:
    async def test_rows_become_findings_and_empty_results_pass(self):
        warehouse = StubWarehouse(
            rows_by_name={"overdue_capa_effectiveness": [{"capa_id": "CAPA-2025-007"}]}
        )
        graph = StubGraph(
            rows_by_method={
                "stale_references": [{"doc_key": "SOP-016", "referenced_doc": "WI-101"}]
            }
        )
        report = await make_runner(warehouse, graph).run()

        by_id = {result.check.check_id: result for result in report.results}
        assert by_id["overdue_capa_effectiveness"].status == "finding"
        assert by_id["stale_document_references"].status == "finding"
        assert by_id["complaints_without_risk_evaluation"].status == "pass"
        assert len(report.results) == len(AUDIT_CHECKS)
        assert len(report.findings) == 2

    async def test_one_failing_check_does_not_sink_the_report(self):
        warehouse = StubWarehouse(fail={"complaint_mdr_reconciliation"})
        report = await make_runner(warehouse).run()

        by_id = {result.check.check_id: result for result in report.results}
        errored = by_id["complaint_mdr_reconciliation"]
        assert errored.status == "error"
        assert "RuntimeError" in errored.detail
        assert len(report.errors) == 1
        assert all(r.status == "pass" for r in report.results if r is not errored)
        assert "1 could not run" in report.summary

    async def test_collection_filter_runs_only_its_checks(self):
        warehouse = StubWarehouse()
        graph = StubGraph()
        report = await make_runner(warehouse, graph).run("design_controls")

        assert report.collection_id == "design_controls"
        assert {r.check.check_id for r in report.results} == {
            "unverified_requirements",
            "fmea_ap_mismatches",
        }
        assert graph.calls == []

    async def test_unknown_collection_lists_available(self):
        with pytest.raises(LookupError, match="design_controls"):
            await make_runner().run("nonexistent")


class StubLLM(LLMProvider):
    def __init__(self, reply: str = "", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        if self.error:
            raise self.error
        return self.reply


def make_report() -> AuditReport:
    return AuditReport(collection_id=None, results=())


class TestAdvisoryNote:
    async def test_valid_json_note_is_used(self):
        llm = StubLLM(reply='{"note": "Pursue the overdue CAPA first."}')
        assert await advisory_note(llm, make_report()) == "Pursue the overdue CAPA first."

    async def test_unparseable_reply_falls_back_to_summary(self):
        report = make_report()
        llm = StubLLM(reply="FAKE_COMPLETION:abc123")
        assert await advisory_note(llm, report) == report.summary

    async def test_provider_error_falls_back_to_summary(self):
        report = make_report()
        llm = StubLLM(error=RuntimeError("provider down"))
        assert await advisory_note(llm, report) == report.summary

    async def test_wrong_shape_falls_back_to_summary(self):
        report = make_report()
        llm = StubLLM(reply='["not", "a", "dict"]')
        assert await advisory_note(llm, report) == report.summary
