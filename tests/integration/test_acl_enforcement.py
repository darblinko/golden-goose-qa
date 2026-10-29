"""Phase 5 ACL acceptance: a restricted user cannot retrieve a restricted
document through any tool path — vector retrieval (Qdrant access_level
filter), warehouse SQL (relation whitelist plus row level security), and
graph anchors — while qa_user and admin retain full access. Each denial is
paired with a privileged control proving the content exists and only the
role stands between the caller and it."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from gg_common.acl import RESTRICTED_DOC_TYPES
from gg_common.providers.factory import build_providers
from gg_common.settings import get_settings
from gg_retrieval.retriever import HybridRetriever
from gg_retrieval.tools.sqlguard import SqlGuardError
from gg_retrieval.tools.warehouse import WarehouseTool
from goldengoose_api.main import create_app
from qdrant_client import AsyncQdrantClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

GENERAL_ONLY = ("general",)
COMPLAINT_QUESTION = "What does complaint C-2025-0142 describe?"
COUNT_QUESTION = "How many complaints were received in 2025?"


def _mint(client, email, role):
    response = client.post("/auth/dev-token", json={"email": email, "role": role})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _parse_sse(lines):
    events, name, data = [], None, []
    for line in lines:
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data.append(line.split(":", 1)[1].strip())
        elif not line.strip() and name is not None:
            events.append((name, json.loads("".join(data)) if data else {}))
            name, data = None, []
    return events


def _chat(client, auth, question):
    created = client.post("/threads", json={}, headers=auth)
    assert created.status_code == 201
    thread_id = created.json()["id"]
    with client.stream(
        "POST", f"/threads/{thread_id}/messages", json={"content": question}, headers=auth
    ) as response:
        assert response.status_code == 200
        events = _parse_sse(response.iter_lines())
    done = [payload for name, payload in events if name == "done"]
    assert len(done) == 1, [name for name, _ in events]
    citations = [payload for name, payload in events if name == "citations"]
    answer = "".join(p["text"] for name, p in events if name == "delta")
    items = citations[0]["items"] if citations else []
    return done[0], items, answer


def test_retrieval_filter_blocks_restricted_chunks(ingested_corpus):
    async def probe():
        settings = get_settings()
        providers = build_providers(settings.providers)
        engine = create_async_engine(settings.postgres.sqlalchemy_url, poolclass=NullPool)
        qdrant = AsyncQdrantClient(url=settings.qdrant.url)
        try:
            retriever = HybridRetriever(
                settings=settings,
                qdrant=qdrant,
                session_factory=async_sessionmaker(engine, expire_on_commit=False),
                embeddings=providers.embeddings,
                reranker=providers.rerank,
            )
            query = "complaint investigation device failure narrative"
            privileged = await retriever.retrieve(query, doc_type="complaint")
            filtered = await retriever.retrieve(
                query, doc_type="complaint", allowed_levels=GENERAL_ONLY
            )
            general = await retriever.retrieve(
                "corrective and preventive action procedure",
                doc_type="sop",
                allowed_levels=GENERAL_ONLY,
            )
            return privileged, filtered, general
        finally:
            await qdrant.close()
            await engine.dispose()

    privileged, filtered, general = asyncio.run(probe())
    # The restricted content exists and is reachable for a privileged caller...
    assert privileged.chunks, "corpus has no complaint chunks — control is broken"
    # ...and the same query under the general-only filter returns nothing.
    assert filtered.chunks == ()
    assert filtered.parents == ()
    # General documents remain reachable under the filter (backfill labeled
    # points indexed before access_level existed).
    assert general.chunks


def test_warehouse_role_narrowing_end_to_end(derived_corpus):
    async def probe():
        settings = get_settings()
        engine = create_async_engine(settings.postgres.sqlalchemy_url, poolclass=NullPool)
        try:
            tool = WarehouseTool(
                session_factory=async_sessionmaker(engine, expire_on_commit=False),
                settings=settings,
            )
            with pytest.raises(SqlGuardError, match="relation not allowed"):
                await tool.run_saved("mdr_register", role="auditor_readonly")
            with pytest.raises(SqlGuardError, match="relation not allowed"):
                await tool.run_sql(
                    "SELECT complaint_id FROM registers.v_complaint_register",
                    role="auditor_readonly",
                )
            allowed = await tool.run_saved("open_ncrs", role="auditor_readonly")
            privileged = await tool.run_saved("mdr_register", role="qa_user")
            return allowed, privileged
        finally:
            await engine.dispose()

    allowed, privileged = asyncio.run(probe())
    assert allowed.tool == "warehouse"  # general registers still answer
    assert privileged.rows, "derived corpus has no MDRs — control is broken"


async def test_rls_backstop_blocks_rows_without_the_flag(derived_corpus, app_engine):
    """Even if the SQL guard were bypassed, the database itself refuses
    restricted rows: sql_tool_ro sees complaint/MDR tables and views only
    when the transaction-local flag is on, and an unset flag reads as off."""
    async with app_engine.connect() as conn:
        await conn.execute(text("SET LOCAL ROLE sql_tool_ro"))
        for relation in (
            "registers.complaint",
            "registers.mdr",
            "registers.v_complaint_register",
            "registers.v_mdr_register",
        ):
            count = (await conn.execute(text(f"SELECT count(*) FROM {relation}"))).scalar()
            assert count == 0, f"{relation} leaked rows with gg.read_restricted unset"
        await conn.rollback()

    async with app_engine.connect() as conn:
        await conn.execute(text("SELECT set_config('gg.read_restricted', 'on', true)"))
        await conn.execute(text("SET LOCAL ROLE sql_tool_ro"))
        count = (
            await conn.execute(text("SELECT count(*) FROM registers.v_complaint_register"))
        ).scalar()
        assert count and count > 0, "flag on returned no complaints — control is broken"
        await conn.rollback()


def test_chat_denies_restricted_content_to_auditor(derived_corpus):
    with TestClient(create_app()) as client:
        auditor = _mint(client, "external.auditor@example.com", "auditor_readonly")
        qa = _mint(client, "qa@example.com", "qa_user")

        # Warehouse path: the count question maps to deterministic SQL over
        # the complaint register, which the auditor's whitelist refuses.
        done, items, answer = _chat(client, auditor, COUNT_QUESTION)
        assert done["verdict"] == "insufficient_evidence"
        assert items == []
        assert "could not answer" in answer  # honest tool-failure text
        qa_done, qa_items, _ = _chat(client, qa, COUNT_QUESTION)
        assert qa_done["verdict"] == "grounded"
        assert qa_items

        # Retrieval path: asking about a specific complaint returns nothing
        # from the restricted families — any answer must come from general
        # documents (e.g. the complaint-handling SOP), never the record text.
        done, items, _ = _chat(client, auditor, COMPLAINT_QUESTION)
        for item in items:
            assert item["doc_type"] not in RESTRICTED_DOC_TYPES, item
            assert item["doc_key"] != "C-2025-0142", item
        qa_done, qa_items, _ = _chat(client, qa, COMPLAINT_QUESTION)
        assert any(i["doc_key"] == "C-2025-0142" for i in qa_items), qa_items


def test_audit_prep_endpoints_require_qa_role(derived_corpus):
    with TestClient(create_app()) as client:
        auditor = _mint(client, "external.auditor@example.com", "auditor_readonly")
        qa = _mint(client, "qa@example.com", "qa_user")

        assert client.get("/audit/collections", headers=auditor).status_code == 403
        assert client.get("/audit/report", headers=auditor).status_code == 403
        assert client.get("/audit/collections", headers=qa).status_code == 200
