"""Graph behavior with canned LLM responses and a stub retriever: routing,
bounded rewrites, citation-gated generation, verifier retry/downgrade, and the
extractive fallback that powers keyless (fake-provider) deployments."""

import hashlib
from typing import cast

from gg_agents.audit import build_turn_audit_event
from gg_agents.graph import build_agent_graph
from gg_agents.nodes import (
    NO_EVIDENCE_ANSWER,
    NOT_IN_CORPUS_ANSWER,
    UNSUPPORTED_ANSWER,
    AgentDeps,
)
from gg_agents.state import AgentState, initial_state
from gg_common.providers.fakes import FakeLLMProvider
from gg_common.settings import AppSettings, ExternalToolSettings
from gg_retrieval.models import ParentContext, RetrievalResult, RetrievedChunk
from gg_retrieval.retriever import HybridRetriever
from gg_retrieval.tools.external.clinicaltrials import ClinicalTrialsTool
from gg_retrieval.tools.external.ecfr import ECFRTool
from gg_retrieval.tools.external.fetch import FakeFetcher
from gg_retrieval.tools.external.models import ExternalResult
from gg_retrieval.tools.external.openfda import OpenFDATool
from gg_retrieval.tools.external.pubmed import PubMedTool
from gg_retrieval.tools.external.toolkit import ExternalToolkit, build_external_toolkit
from gg_retrieval.tools.external.websearch import FakeWebSearchProvider, WebSearchTool
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.models import ToolResult
from gg_retrieval.tools.warehouse import WarehouseTool

QUESTION = "What does SOP-004 require for effectiveness verification?"

CHUNK = RetrievedChunk(
    chunk_id="11111111-1111-5111-8111-111111111111",
    doc_key="SOP-004",
    doc_type="sop",
    title="Corrective and Preventive Action",
    revision="C",
    section_path="3. Procedure",
    text="Effectiveness verification is required within 90 days of closure.",
    context_header="SOP-004 Rev C — Corrective and Preventive Action (sop)",
    score=0.9,
    parent_id="22222222-2222-5222-8222-222222222222",
)

PARENT = ParentContext(
    parent_id="22222222-2222-5222-8222-222222222222",
    doc_key="SOP-004",
    doc_type="sop",
    title="Corrective and Preventive Action",
    revision="C",
    section_path="3. Procedure",
    text="Effectiveness verification is required within 90 days of closure.",
    context_header="SOP-004 Rev C — Corrective and Preventive Action (sop)",
    best_child_score=0.9,
)

PARENT2 = ParentContext(
    parent_id="33333333-3333-5333-8333-333333333333",
    doc_key="SOP-012",
    doc_type="sop",
    title="Document Control",
    revision="A",
    section_path="2. Scope",
    text="Obsolete documents are removed from points of use.",
    context_header="SOP-012 Rev A — Document Control (sop)",
    best_child_score=0.8,
)


class StubRetriever:
    def __init__(self, parents: list[ParentContext], chunks: list[RetrievedChunk]):
        self.parents = parents
        self.chunks = chunks
        self.calls: list[dict] = []
        self.levels: list[tuple[str, ...] | None] = []

    async def retrieve(
        self,
        query,
        *,
        doc_type=None,
        doc_key=None,
        revision=None,
        status=None,
        as_of=None,
        top_k=None,
        allowed_levels=None,
    ):
        self.calls.append(
            {
                "query": query,
                "doc_type": doc_type,
                "doc_key": doc_key,
                "revision": revision,
                "as_of": as_of,
            }
        )
        self.levels.append(allowed_levels)
        return RetrievalResult(
            query=query, chunks=tuple(self.chunks), parents=tuple(self.parents), timings_ms={}
        )


WAREHOUSE_RESULT = ToolResult(
    tool="warehouse",
    title="Count of complaints in 2024",
    source="registers warehouse (ad-hoc SQL)",
    query="SELECT count(*) AS total FROM registers.v_complaint_register ...",
    columns=("total",),
    rows=({"total": 25},),
)

TRACE_RESULT = ToolResult(
    tool="graph_walk",
    title="Requirement trace: REQ-001",
    source="knowledge graph (derived from corpus extraction)",
    query="requirement_trace(REQ-001)",
    columns=("relation", "from_key", "to_key", "detail", "source_doc"),
    rows=(
        {
            "relation": "VERIFIES",
            "from_key": "VTR-001",
            "to_key": "REQ-001",
            "detail": "protocol VTP-001, result Pass",
            "source_doc": "TM-100",
        },
    ),
    source_doc_keys=("TM-100",),
)

UNVERIFIED_RESULT = ToolResult(
    tool="graph_walk",
    title="Requirements with no verification report",
    source="knowledge graph (derived from corpus extraction)",
    query="unverified_requirements()",
    columns=("req_id", "category", "requirement_text", "source_doc", "locator"),
    rows=(
        {
            "req_id": "REQ-017",
            "category": "Safety",
            "requirement_text": "Device shall not exceed 43 C surface temperature.",
            "source_doc": "TM-100",
            "locator": "row 17",
        },
    ),
    source_doc_keys=("TM-100",),
)


THREAD_RESULT = ToolResult(
    tool="graph_walk",
    title="Record thread around CAPA-2025-014 (up to 3 hops)",
    source="knowledge graph (derived from corpus extraction)",
    query="record_thread(CAPA-2025-014)",
    columns=("relation", "from_key", "to_key", "detail", "source_doc"),
    rows=(
        {
            "relation": "ESCALATED_TO",
            "from_key": "NCR-2025-011",
            "to_key": "CAPA-2025-014",
            "detail": "",
            "source_doc": "NCR-2025-011",
        },
        {
            "relation": "SOURCED_FROM",
            "from_key": "CAPA-2025-014",
            "to_key": "C-2025-0142",
            "detail": "",
            "source_doc": "CAPA-2025-014",
        },
    ),
    source_doc_keys=("NCR-2025-011", "CAPA-2025-014"),
)


class StubWarehouse:
    def __init__(self, result: ToolResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.saved_calls: list[tuple[str, dict | None]] = []
        self.sql_calls: list[str] = []
        self.roles: list[str] = []

    async def run_saved(self, name, params=None, *, role="admin"):
        self.saved_calls.append((name, params))
        self.roles.append(role)
        if self.error:
            raise self.error
        return self.result

    async def run_sql(self, sql, *, title="Ad-hoc register query", role="admin"):
        self.sql_calls.append(sql)
        self.roles.append(role)
        if self.error:
            raise self.error
        return self.result


MISSING_ANCHOR_RESULT = ToolResult(
    tool="graph_walk",
    title="Training status for WI-MFG-014 (not in graph)",
    source="knowledge graph (derived from corpus extraction)",
    query="training_status(WI-MFG-014)",
    columns=("person", "role", "trained_revision", "trained_on", "current_revision"),
    rows=(),
    anchor_missing=True,
)


class StubGraphWalker:
    def __init__(self, result: ToolResult):
        self.result = result
        self.calls: list[tuple[str, str | None]] = []

    async def requirement_trace(self, req_id):
        self.calls.append(("requirement_trace", req_id))
        return self.result

    async def training_status(self, doc_key):
        self.calls.append(("training_status", doc_key))
        return self.result

    async def document_profile(self, doc_key):
        self.calls.append(("document_profile", doc_key))
        return self.result

    async def unverified_requirements(self):
        self.calls.append(("unverified_requirements", None))
        return self.result

    async def record_thread(self, doc_key):
        self.calls.append(("record_thread", doc_key))
        return self.result


def make_deps(
    canned: dict[str, str],
    retriever: StubRetriever,
    *,
    llm_is_fake=False,
    warehouse=None,
    graph=None,
    external=None,
):
    return AgentDeps(
        settings=AppSettings(),
        retriever=cast(HybridRetriever, retriever),
        llm=FakeLLMProvider(canned=canned),
        llm_is_fake=llm_is_fake,
        warehouse=cast(WarehouseTool, warehouse) if warehouse else None,
        graph=cast(GraphWalker, graph) if graph else None,
        external=external,
    )


MAUDE_QUESTION = "Compare our infusion pump complaints against MAUDE adverse events"


def offline_toolkit() -> ExternalToolkit:
    return build_external_toolkit(ExternalToolSettings(offline=True))


def broken_toolkit() -> ExternalToolkit:
    """Every fetch raises: exercises graceful degradation to internal-only."""
    settings = ExternalToolSettings()
    fetcher = FakeFetcher(())
    return ExternalToolkit(
        openfda=OpenFDATool(fetcher, settings),
        ecfr=ECFRTool(fetcher, settings),
        clinicaltrials=ClinicalTrialsTool(fetcher, settings),
        pubmed=PubMedTool(fetcher, settings),
        websearch=WebSearchTool(FakeWebSearchProvider(), settings),
    )


# Needle order matters: FakeLLMProvider matches the first needle found in the
# last message, and "Cited sources:" must win over "Sources:".
def canned_responses(**overrides: str) -> dict[str, str]:
    canned = {
        "Cited sources:": '{"grounded": true, "unsupported_claims": []}',
        "Excerpts:": '{"sufficient": true, "reason": "on point"}',
        "Failed query:": "CAPA effectiveness verification SOP-004",
        "Sources:": "Verification is required within 90 days [1].",
        QUESTION: '{"pattern": "procedure", "doc_type": "sop"}',
    }
    canned.update(overrides)
    return canned


async def test_happy_path_is_grounded_and_cited():
    retriever = StubRetriever([PARENT], [CHUNK])
    graph = build_agent_graph(make_deps(canned_responses(), retriever))
    final = await graph.ainvoke(initial_state(QUESTION))

    assert final["pattern"] == "procedure"
    # QUESTION names exactly one document (SOP-004), so its deterministic doc_key
    # scope threads into retrieval alongside the LLM-routed doc_type.
    assert retriever.calls == [
        {
            "query": QUESTION,
            "doc_type": "sop",
            "doc_key": "SOP-004",
            "revision": None,
            "as_of": None,
        }
    ]
    assert final["verdict"] == "grounded"
    assert final["answer"] == "Verification is required within 90 days [1]."
    assert [c["doc_key"] for c in final["citations"]] == ["SOP-004"]
    assert final["citations"][0]["citation"] == "SOP-004 Rev C, 3. Procedure"
    assert final["prompt_hash"]
    assert final["verifier_error"] is None


async def test_unparseable_route_defaults_to_unfiltered_retrieval():
    retriever = StubRetriever([PARENT], [CHUNK])
    canned = canned_responses(**{QUESTION: "not json at all"})
    graph = build_agent_graph(make_deps(canned, retriever))
    final = await graph.ainvoke(initial_state(QUESTION))
    assert final["pattern"] == "record"
    assert retriever.calls[0]["doc_type"] is None
    assert final["verdict"] == "grounded"


async def test_empty_retrieval_rewrites_twice_then_answers_honestly():
    retriever = StubRetriever([], [])
    graph = build_agent_graph(make_deps(canned_responses(), retriever))
    final = await graph.ainvoke(initial_state(QUESTION))

    assert len(retriever.calls) == 3  # initial + MAX_REWRITES
    assert retriever.calls[1]["query"] == "CAPA effectiveness verification SOP-004"
    assert final["verdict"] == "insufficient_evidence"
    assert final["answer"] == NO_EVIDENCE_ANSWER
    assert final["citations"] == []


async def test_explicit_revision_scope_threads_and_persists_across_rewrites():
    # A question naming one document and one revision must carry that exact scope
    # into retrieval and keep it across the rewrite loop, so a rewritten query can
    # never widen to a neighboring document or revision.
    scoped_q = "What did Rev A of SOP-004 require for effectiveness verification?"
    retriever = StubRetriever([], [])  # empty results exhaust the rewrite loop
    canned = canned_responses(**{scoped_q: '{"pattern": "procedure", "doc_type": "sop"}'})
    graph = build_agent_graph(make_deps(canned, retriever))
    final = await graph.ainvoke(initial_state(scoped_q))

    assert final["doc_key"] == "SOP-004"
    assert final["revision"] == "A"
    assert len(retriever.calls) == 3  # initial + MAX_REWRITES
    assert all(c["doc_key"] == "SOP-004" and c["revision"] == "A" for c in retriever.calls)
    assert final["verdict"] == "insufficient_evidence"


async def test_count_question_answers_from_warehouse_without_retrieval():
    retriever = StubRetriever([PARENT], [CHUNK])
    warehouse = StubWarehouse(result=WAREHOUSE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, warehouse=warehouse)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state("How many complaints were received in 2024?"))

    assert retriever.calls == []
    assert final["pattern"] == "aggregate"
    assert len(warehouse.sql_calls) == 1
    assert "registers.v_complaint_register" in warehouse.sql_calls[0]
    assert final["verdict"] == "grounded"
    assert "25" in final["answer"]
    assert "[1]" in final["answer"]
    assert final["citations"][0]["doc_type"] == "tool_result"
    assert "Count of complaints in 2024" in final["citations"][0]["citation"]


async def test_overdue_effectiveness_uses_saved_query():
    retriever = StubRetriever([], [])
    warehouse = StubWarehouse(result=WAREHOUSE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, warehouse=warehouse)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state("Are any CAPA effectiveness checks overdue?"))
    assert warehouse.saved_calls == [("overdue_capa_effectiveness", None)]
    assert final["verdict"] == "grounded"


async def test_requirement_trace_answers_from_graph():
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(TRACE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(
        initial_state("Which verification reports provide objective evidence for REQ-001?")
    )

    assert retriever.calls == []
    assert final["pattern"] == "trace"
    assert walker.calls == [("requirement_trace", "REQ-001")]
    assert final["verdict"] == "grounded"
    assert "VTP-001" in final["answer"]
    citation = final["citations"][0]
    assert citation["doc_type"] == "tool_result"
    # The citation names the real evidence document, not the synthetic graph
    # banner, and carries the resolvable source doc key for the panel.
    assert citation["doc_key"] == "TM-100"
    assert "TM-100" in citation["citation"]
    assert "knowledge graph" not in citation["citation"]
    assert citation["source_doc_keys"] == ["TM-100"]


async def test_unverified_requirement_cites_its_source_document():
    # An unverified requirement is a grounded compliance finding; its citation
    # must resolve to the exact document and row, never to "knowledge graph."
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(UNVERIFIED_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(
        initial_state("Do all requirements have verification evidence? Which lack it?")
    )

    assert walker.calls == [("unverified_requirements", None)]
    assert final["verdict"] == "grounded"
    assert "REQ-017" in final["answer"]
    citation = final["citations"][0]
    assert citation["doc_key"] == "TM-100"
    assert citation["source_doc_keys"] == ["TM-100"]
    assert "knowledge graph" not in citation["citation"]


async def test_capa_thread_question_walks_the_record_thread():
    # "Walk me through CAPA-2025-014 end to end" must reach record_thread with
    # the full id and answer from the graph hops, citing the source documents —
    # never fall through to vector retrieval.
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(THREAD_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state("Walk me through CAPA-2025-014 end to end."))

    assert retriever.calls == []
    assert final["pattern"] == "trace"
    assert walker.calls == [("record_thread", "CAPA-2025-014")]
    assert final["verdict"] == "grounded"
    assert "NCR-2025-011" in final["answer"]
    citation = final["citations"][0]
    assert citation["source_doc_keys"] == ["NCR-2025-011", "CAPA-2025-014"]
    assert "knowledge graph" not in citation["citation"]


async def test_training_question_walks_the_graph():
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(TRACE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(
        initial_state("Is Sarah Lindqvist trained to the current revision of SOP-001?")
    )
    assert walker.calls == [("training_status", "SOP-001")]
    assert final["verdict"] == "grounded"


async def test_missing_graph_anchor_answers_not_in_corpus_not_grounded():
    # A training question for a document absent from the graph (the WI-MFG-014
    # acceptance case) must resolve to insufficient_evidence, never a grounded
    # "(no matching rows)" citation.
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(MISSING_ANCHOR_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(
        initial_state("Is the operator trained to the current revision of WI-MFG-014?")
    )
    assert walker.calls == [("training_status", "WI-MFG-014")]
    assert final["verdict"] == "insufficient_evidence"
    assert final["citations"] == []
    assert "WI-MFG-014" in final["answer"]
    assert final["answer"] == NOT_IN_CORPUS_ANSWER.format(anchor=MISSING_ANCHOR_RESULT.title)


async def test_warehouse_failure_is_honest():
    retriever = StubRetriever([], [])
    warehouse = StubWarehouse(error=RuntimeError("connection refused"))
    deps = make_deps({}, retriever, llm_is_fake=True, warehouse=warehouse)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state("How many complaints were received in 2024?"))
    assert final["verdict"] == "insufficient_evidence"
    assert "connection refused" in final["answer"]
    assert final["citations"] == []


async def test_unconfigured_tools_answer_honestly():
    retriever = StubRetriever([], [])
    graph = build_agent_graph(make_deps({}, retriever, llm_is_fake=True))
    final = await graph.ainvoke(initial_state("How many complaints were received in 2024?"))
    assert final["verdict"] == "insufficient_evidence"
    assert "not configured" in final["answer"]


async def test_uncited_answer_regenerates_once_then_downgrades():
    retriever = StubRetriever([PARENT], [CHUNK])
    canned = canned_responses(**{"Sources:": "A claim with no marker at all."})
    deps = make_deps(canned, retriever)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state(QUESTION))

    llm = cast(FakeLLMProvider, deps.llm)
    generate_calls = [c for c in llm.calls if "Sources:" in c[1].content]
    assert len(generate_calls) == 2  # first attempt + corrective retry
    assert "failed citation verification" in generate_calls[1][-1].content
    assert final["verdict"] == "insufficient_evidence"
    assert final["answer"] == UNSUPPORTED_ANSWER
    # Retrieved sources stay attached for manual review even without citations.
    assert [c["doc_key"] for c in final["citations"]] == ["SOP-004"]


async def test_unparseable_verifier_output_withholds_after_retry():
    retriever = StubRetriever([PARENT], [CHUNK])
    # The verifier response is unparseable on every attempt; the corrective
    # regeneration keeps a marker so the second verify re-reaches the verifier.
    canned = canned_responses(
        **{
            "Cited sources:": "not json at all",
            "Restate it": "Verification is required within 90 days [1].",
        }
    )
    deps = make_deps(canned, retriever)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state(QUESTION))

    llm = cast(FakeLLMProvider, deps.llm)
    verifier_calls = [c for c in llm.calls if "Cited sources:" in c[-1].content]
    assert len(verifier_calls) == 2  # first attempt + post-regeneration attempt
    assert final["verdict"] == "insufficient_evidence"
    assert final["answer"] == UNSUPPORTED_ANSWER
    assert final["verifier_error"] == "verifier response unparseable"


async def test_verifier_sees_original_citation_markers():
    retriever = StubRetriever([PARENT, PARENT2], [CHUNK])
    canned = canned_responses(**{"Sources:": "Obsolete documents are removed [2]."})
    deps = make_deps(canned, retriever)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state(QUESTION))

    llm = cast(FakeLLMProvider, deps.llm)
    verifier_calls = [c for c in llm.calls if "Cited sources:" in c[-1].content]
    assert len(verifier_calls) == 1
    body = verifier_calls[0][-1].content
    assert "[2] SOP-012" in body  # the cited source keeps the answer's marker
    assert "[1] SOP-012" not in body  # never renumbered to a 1..k subset
    assert final["verdict"] == "grounded"
    assert final["citations"][0]["marker"] == 2
    assert final["citations"][0]["doc_key"] == "SOP-012"


async def test_generator_admitting_insufficiency_is_honest():
    retriever = StubRetriever([PARENT], [CHUNK])
    canned = canned_responses(**{"Sources:": "INSUFFICIENT_EVIDENCE"})
    graph = build_agent_graph(make_deps(canned, retriever))
    final = await graph.ainvoke(initial_state(QUESTION))
    assert final["verdict"] == "insufficient_evidence"
    assert final["answer"] == NO_EVIDENCE_ANSWER


async def test_keyless_mode_produces_grounded_extractive_answer():
    retriever = StubRetriever([PARENT], [CHUNK])
    graph = build_agent_graph(make_deps({}, retriever, llm_is_fake=True))
    final = await graph.ainvoke(initial_state(QUESTION))

    assert final["verdict"] == "grounded"
    assert final["answer"].startswith("Extractive answer")
    assert "[1]" in final["answer"]
    assert [c["doc_key"] for c in final["citations"]] == ["SOP-004"]
    assert final["verifier_error"] == "fake llm: entailment not evaluated"


async def test_maude_comparison_combines_internal_and_external_citations():
    retriever = StubRetriever([PARENT], [CHUNK])
    deps = make_deps({}, retriever, llm_is_fake=True, external=offline_toolkit())
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(initial_state(MAUDE_QUESTION))

    assert final["pattern"] == "external"
    assert len(retriever.calls) == 1  # internal retrieval still ran
    assert final["verdict"] == "grounded"
    assert "EXTERNAL SOURCE (not QMS evidence)" in final["answer"]
    assert "SYNTH-MAUDE-0001" in final["answer"]
    assert [c["provenance"] for c in final["citations"]] == ["internal", "external"]
    assert final["citations"][0]["doc_key"] == "SOP-004"
    assert final["citations"][1]["citation"].endswith("[EXTERNAL]")


async def test_external_failure_degrades_to_internal_only_answer():
    retriever = StubRetriever([PARENT], [CHUNK])
    deps = make_deps({}, retriever, llm_is_fake=True, external=broken_toolkit())
    final = await build_agent_graph(deps).ainvoke(initial_state(MAUDE_QUESTION))

    assert final["verdict"] == "grounded"
    assert final["external_parents"] == []
    assert final["external_error"]
    assert "external data sources could not be reached" in final["answer"]
    assert all(c["provenance"] == "internal" for c in final["citations"])
    assert "EXTERNAL SOURCE" not in final["answer"]


async def test_external_evidence_alone_supports_an_answer():
    retriever = StubRetriever([], [])
    deps = make_deps({}, retriever, llm_is_fake=True, external=offline_toolkit())
    final = await build_agent_graph(deps).ainvoke(initial_state(MAUDE_QUESTION))

    assert len(retriever.calls) == 3  # initial + exhausted rewrites
    assert final["verdict"] == "grounded"
    assert [c["provenance"] for c in final["citations"]] == ["external"]
    assert "EXTERNAL SOURCE (not QMS evidence)" in final["answer"]


COMPARE_QUESTION = "How does our complaint rate for this device class compare to MAUDE?"

COMPARE_COUNT_RESULT = ToolResult(
    tool="warehouse",
    title="Complaint count",
    source="registers warehouse (ad-hoc SQL)",
    query="SELECT count(*) AS complaints FROM registers.v_complaint_register",
    columns=("complaints",),
    rows=({"complaints": 25},),
)


async def test_rate_comparison_refuses_without_a_shared_denominator():
    # The MAUDE acceptance case. A rate question routes to compare (not the
    # one-sided external lookup and never vector retrieval), runs the warehouse
    # count and the MAUDE lookup together, and — with no device-population
    # denominator on either side — refuses with insufficient_evidence while
    # surfacing both figures as separated internal/external evidence.
    from gg_agents.nodes import COMPARE_INSUFFICIENT_ANSWER

    retriever = StubRetriever([PARENT], [CHUNK])
    warehouse = StubWarehouse(result=COMPARE_COUNT_RESULT)
    deps = make_deps(
        {}, retriever, llm_is_fake=True, warehouse=warehouse, external=offline_toolkit()
    )
    final = await build_agent_graph(deps).ainvoke(initial_state(COMPARE_QUESTION))

    assert final["pattern"] == "compare"
    assert retriever.calls == []  # no vector retrieval — the defect being fixed
    assert warehouse.sql_calls == [
        "SELECT count(*) AS complaints FROM registers.v_complaint_register"
    ]
    assert final["verdict"] == "insufficient_evidence"
    assert final["answer"] == COMPARE_INSUFFICIENT_ANSWER
    assert [c["provenance"] for c in final["citations"]] == ["internal", "external"]
    assert final["citations"][1]["citation"].endswith("[EXTERNAL]")
    # The validated openFDA total (meta.results.total) is consumed and surfaced,
    # not the two-row page length.
    assert (
        "Total matching records reported by the source: 128"
        in (final["external_parents"][0]["text"])
    )


def test_rate_denominators_resolve_only_when_both_populations_present():
    from gg_agents.nodes import _rate_denominators

    internal = ToolResult(
        tool="warehouse",
        title="Complaint count",
        source="registers warehouse (ad-hoc SQL)",
        query="q",
        columns=("complaints", "device_population"),
        rows=({"complaints": 25, "device_population": 5000},),
    )
    external = ExternalResult(
        tool="openfda_maude",
        title="MAUDE",
        source="openFDA device/event API",
        query="infusion pump",
        url="https://api.fda.gov/device/event.json",
        columns=("installed_base",),
        rows=({"installed_base": 900000},),
        total=128,
    )
    assert _rate_denominators(internal, external) == (5000, 900000)
    # Missing either population (the real register/openFDA surface) → refuse.
    assert _rate_denominators(internal, None) is None
    assert _rate_denominators(None, None) is None


async def test_rate_comparison_without_tools_still_refuses_honestly():
    retriever = StubRetriever([PARENT], [CHUNK])
    deps = make_deps({}, retriever, llm_is_fake=True)
    final = await build_agent_graph(deps).ainvoke(initial_state(COMPARE_QUESTION))

    assert final["pattern"] == "compare"
    assert retriever.calls == []
    assert final["verdict"] == "insufficient_evidence"
    assert final["citations"] == []


async def test_unconfigured_external_tools_fall_back_to_internal_retrieval():
    retriever = StubRetriever([PARENT], [CHUNK])
    deps = make_deps({}, retriever, llm_is_fake=True)
    final = await build_agent_graph(deps).ainvoke(initial_state(MAUDE_QUESTION))

    assert final["pattern"] == "external"
    assert final["verdict"] == "grounded"
    assert all(c["provenance"] == "internal" for c in final["citations"])


async def test_auditor_retrieval_is_level_filtered():
    retriever = StubRetriever([PARENT], [CHUNK])
    graph = build_agent_graph(make_deps(canned_responses(), retriever))
    final = await graph.ainvoke(initial_state(QUESTION, role="auditor_readonly"))
    assert retriever.levels == [("general",)]
    assert final["verdict"] == "grounded"  # general content still answers


async def test_privileged_role_retrieves_unfiltered():
    retriever = StubRetriever([PARENT], [CHUNK])
    graph = build_agent_graph(make_deps(canned_responses(), retriever))
    await graph.ainvoke(initial_state(QUESTION, role="qa_user"))
    assert retriever.levels == [None]


def test_missing_role_fails_closed():
    from gg_agents.nodes import _retrieval_levels, _state_role

    assert _state_role(cast(AgentState, {})) == "auditor_readonly"
    assert _state_role(cast(AgentState, {"role": ""})) == "auditor_readonly"
    assert _state_role(cast(AgentState, {"role": "qa_user"})) == "qa_user"
    assert _retrieval_levels(cast(AgentState, {})) == ("general",)
    assert _retrieval_levels(cast(AgentState, {"role": "admin"})) is None


async def test_warehouse_receives_caller_role():
    retriever = StubRetriever([], [])
    warehouse = StubWarehouse(result=WAREHOUSE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, warehouse=warehouse)
    graph = build_agent_graph(deps)
    await graph.ainvoke(
        initial_state("How many complaints were received in 2024?", role="auditor_readonly")
    )
    assert warehouse.roles == ["auditor_readonly"]


async def test_restricted_graph_anchor_blocked_for_auditor():
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(TRACE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(
        initial_state(
            "Is Sarah Lindqvist trained to the current revision of MDR-100?",
            role="auditor_readonly",
        )
    )
    assert walker.calls == []  # blocked before the graph is touched
    assert final["verdict"] == "insufficient_evidence"
    assert "qa_user or admin role" in final["answer"]


async def test_restricted_graph_anchor_allowed_for_qa_user():
    retriever = StubRetriever([], [])
    walker = StubGraphWalker(TRACE_RESULT)
    deps = make_deps({}, retriever, llm_is_fake=True, graph=walker)
    graph = build_agent_graph(deps)
    final = await graph.ainvoke(
        initial_state(
            "Is Sarah Lindqvist trained to the current revision of MDR-100?", role="qa_user"
        )
    )
    assert walker.calls == [("training_status", "MDR-100")]
    assert final["verdict"] == "grounded"


async def test_turn_audit_event_records_provenance():
    retriever = StubRetriever([PARENT], [CHUNK])
    settings = AppSettings()
    graph = build_agent_graph(make_deps(canned_responses(), retriever))
    final = await graph.ainvoke(initial_state(QUESTION))

    event = build_turn_audit_event(
        cast(AgentState, final), settings=settings, thread_id="thread-1", actor="user@example.test"
    )
    assert event.action == "chat.turn"
    assert event.payload["thread_id"] == "thread-1"
    assert event.payload["chunk_ids"] == [CHUNK.chunk_id]
    assert event.payload["cited"] == ["SOP-004 Rev C, 3. Procedure"]
    assert event.payload["model"] == settings.providers.llm_model
    assert event.payload["prompt_hash"] == final["prompt_hash"]
    assert event.payload["verdict"] == "grounded"
    # The immutable record carries the answer itself and what it rested on.
    assert event.payload["answer"] == final["answer"]
    assert event.payload["answer_sha256"] == hashlib.sha256(final["answer"].encode()).hexdigest()
    citation = event.payload["citations"][0]
    assert citation["doc_key"] == "SOP-004"
    assert citation["marker"] == 1
    evidence = event.payload["evidence"]
    assert [e["parent_id"] for e in evidence] == [p["parent_id"] for p in final["parents"]]
    assert (
        evidence[0]["text_sha256"]
        == hashlib.sha256(final["parents"][0]["text"].encode()).hexdigest()
    )


async def test_turn_emits_spans_for_each_node():
    from gg_common.settings import TracingSettings
    from gg_common.tracing import configure_tracing, reset_tracing
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    configure_tracing(TracingSettings(enabled=True), exporter=exporter)
    try:
        retriever = StubRetriever([PARENT], [CHUNK])
        graph = build_agent_graph(make_deps(canned_responses(), retriever))
        await graph.ainvoke(initial_state(QUESTION))
    finally:
        names = {s.name for s in exporter.get_finished_spans()}
        reset_tracing()
    assert {"agent.route", "agent.retrieve", "agent.grade", "agent.generate", "agent.verify"} <= (
        names
    )
