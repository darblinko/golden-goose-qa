"""Agent acceptance against the live stack: deterministic tool routes answer
the golden warehouse and graph questions end-to-end (real Postgres registers,
real Neo4j graph, fake LLM so the extractive path carries the tool output).

These cover the questions the retrieval eval must skip (corpus: pseudo-ids)
plus the three seeded defects an auditor is expected to find: REQ-017 lacks
verification, CAPA-2025-007 has an overdue effectiveness check, and complaint
C-2025-0142 was never evaluated against the risk management file. A fourth
scenario exercises the record-thread walk: CAPA-2025-014 is seeded with a
walkable dossier (complaint source and escalating NCR) the agent must traverse.
"""

from typing import Any, cast

import pytest
from gg_agents.graph import build_agent_graph
from gg_agents.nodes import AgentDeps
from gg_agents.state import initial_state
from gg_common.graphstore import create_graph_driver
from gg_common.providers.fakes import FakeLLMProvider
from gg_common.settings import get_settings
from gg_retrieval.retriever import HybridRetriever
from gg_retrieval.tools.graph_walk import GraphWalker
from gg_retrieval.tools.warehouse import REGISTER_VIEWS, WarehouseTool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration


async def test_register_views_match_live_schema(app_engine):
    """REGISTER_VIEWS is the tool's whole SQL surface; drift between the map
    and migration 0004 must fail loudly (promised in warehouse.py)."""
    async with app_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns"
                " WHERE table_schema = 'registers' AND table_name LIKE 'v\\_%'"
                " ORDER BY table_name, ordinal_position"
            )
        )
        columns_by_view: dict[str, list[str]] = {}
        for table_name, column_name in rows:
            columns_by_view.setdefault(f"registers.{table_name}", []).append(column_name)
        live = {view: tuple(columns) for view, columns in columns_by_view.items()}
    assert live == REGISTER_VIEWS


@pytest.fixture
async def audit_agent(app_engine, derived_corpus: dict[str, Any]):
    settings = get_settings()
    driver = create_graph_driver(settings.neo4j)
    deps = AgentDeps(
        settings=settings,
        # Every question here hits a deterministic tool route, so the
        # retriever is never called; None keeps the fixture honest about that.
        retriever=cast(HybridRetriever, None),
        llm=FakeLLMProvider(canned={}),
        llm_is_fake=True,
        warehouse=WarehouseTool(
            session_factory=async_sessionmaker(app_engine, expire_on_commit=False),
            settings=settings,
        ),
        graph=GraphWalker(driver=driver, settings=settings),
    )
    yield build_agent_graph(deps)
    await driver.close()


async def _ask(agent, question: str) -> dict[str, Any]:
    final = await agent.ainvoke(initial_state(question))
    assert final["verdict"] == "grounded", final["answer"]
    assert final["citations"], final["answer"]
    return final


async def test_complaint_count_2024(audit_agent):
    final = await _ask(audit_agent, "How many complaints were received in 2024?")
    assert final["pattern"] == "aggregate"
    assert "Count of complaints in 2024" in final["answer"]
    assert "total\n25" in final["answer"]


async def test_ncr_count_2024(audit_agent):
    final = await _ask(audit_agent, "How many NCRs were opened in 2024?")
    assert final["pattern"] == "aggregate"
    assert "total\n15" in final["answer"]


async def test_capa_count_2024(audit_agent):
    final = await _ask(audit_agent, "How many CAPAs were opened in 2024?")
    assert final["pattern"] == "aggregate"
    assert "total\n9" in final["answer"]


async def test_overdue_effectiveness_finds_seeded_capa(audit_agent):
    question = "As of 2026-07-01, are any CAPA effectiveness checks overdue?"
    final = await _ask(audit_agent, question)
    assert final["pattern"] == "aggregate"
    assert "CAPA-2025-007" in final["answer"]


async def test_complaint_risk_gap_finds_seeded_complaint(audit_agent):
    question = "Were all complaints evaluated against the risk management file?"
    final = await _ask(audit_agent, question)
    assert final["pattern"] == "aggregate"
    assert "C-2025-0142" in final["answer"]


async def test_requirement_trace_walks_the_graph(audit_agent):
    question = "Which verification reports provide objective evidence for REQ-001?"
    final = await _ask(audit_agent, question)
    assert final["pattern"] == "trace"
    assert "VTR-001" in final["answer"]
    assert "VTR-002" in final["answer"]


async def test_unverified_requirements_finds_req_017(audit_agent):
    question = "Do all design input requirements have verification evidence?"
    final = await _ask(audit_agent, question)
    assert final["pattern"] == "trace"
    assert "REQ-017" in final["answer"]


async def test_training_status_for_current_revision(audit_agent):
    question = "Is Sarah Lindqvist trained to the current revision of SOP-001?"
    final = await _ask(audit_agent, question)
    assert final["pattern"] == "trace"
    assert "Sarah Lindqvist" in final["answer"]
    assert "SOP-001" in final["answer"]


async def test_capa_thread_walk_traverses_the_record(audit_agent):
    """The full CAPA id anchors a record_thread walk that surfaces the seeded
    dossier: the escalating NCR and the source complaint, not a bare total."""
    question = "Walk me through CAPA-2025-014 end to end."
    final = await _ask(audit_agent, question)
    assert final["pattern"] == "trace"
    assert "CAPA-2025-014" in final["answer"]
    assert "NCR-2025-001" in final["answer"]
    assert "C-2025-0101" in final["answer"]
