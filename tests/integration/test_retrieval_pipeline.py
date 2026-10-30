"""End-to-end M1 proof against live services: the shared session fixture
generates and ingests the seeded corpus (Postgres registry + SeaweedFS
objects + Qdrant hybrid index), then this test runs the health probe and the
smoke QA eval through the real retriever.

The recall gate here is the same one CI enforces: with deterministic fake
providers, BM25 sparse + token-overlap rerank must reach recall@10 >= 0.8
on the smoke set. A drop means chunking, indexing, or fusion regressed.
"""

from datetime import date

import pytest
from gg_common.providers.factory import build_providers
from gg_common.settings import get_settings
from gg_evals.cli import load_items
from gg_evals.retrieval_eval import evaluate
from gg_ingestion.indexer import make_client
from gg_retrieval.health import retrieval_health
from gg_retrieval.retriever import HybridRetriever
from sqlalchemy.ext.asyncio import async_sessionmaker

pytestmark = pytest.mark.integration

SMOKE_GATE = 0.8
# The counts_aggregates smoke items carry no document evidence; they are
# answered by the record warehouse instead and covered in
# test_agent_acceptance.py. The count is _SMOKE_QUOTA["counts_aggregates"] in
# gg_synthdata.qa.
AGGREGATE_SKIPS = 2


async def test_ingest_retrieve_eval_end_to_end(ingested_corpus, app_engine):
    report = ingested_corpus["report"]
    counts = report.counts()
    # Phase 4 OCR path: every corpus file ingests, including the scanned DHRs
    assert counts.get("skipped_unsupported", 0) == 0
    assert counts.get("failed", 0) == 0
    ingested = counts.get("indexed", 0) + counts.get("unchanged", 0)
    assert ingested == len(report.results)

    settings = get_settings()
    providers = build_providers(settings.providers)
    qdrant = make_client(settings.qdrant)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    try:
        retriever = HybridRetriever(
            settings=settings,
            qdrant=qdrant,
            session_factory=session_factory,
            embeddings=providers.embeddings,
            reranker=providers.rerank,
        )

        health = await retrieval_health(retriever)
        assert health["healthy"], health
        assert health["probe"]["n_parents"] > 0

        items = load_items(ingested_corpus["root"] / "qa" / "golden_qa.json")
        eval_report = await evaluate(retriever, items, smoke_only=True)
        aggregate_smoke_ids = {
            item.id for item in items if item.smoke and item.pattern == "counts_aggregates"
        }
        assert set(eval_report.skipped) == aggregate_smoke_ids, eval_report.skipped
        assert len(eval_report.skipped) == AGGREGATE_SKIPS, eval_report.skipped
        assert eval_report.results, "no evaluable smoke items"
        assert eval_report.recall >= SMOKE_GATE, eval_report.as_dict()
    finally:
        await qdrant.close()


async def test_as_of_returns_the_revision_effective_on_that_date(ingested_corpus, app_engine):
    """SOP-004 ships as an effective Rev B plus an archived, obsolete Rev A.
    An as-of date inside Rev A's effective window must surface only Rev A;
    the default (current-state) path must surface only Rev B."""
    settings = get_settings()
    providers = build_providers(settings.providers)
    qdrant = make_client(settings.qdrant)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    try:
        retriever = HybridRetriever(
            settings=settings,
            qdrant=qdrant,
            session_factory=session_factory,
            embeddings=providers.embeddings,
            reranker=providers.rerank,
        )
        query = "corrective and preventive action effectiveness verification"

        current = await retriever.retrieve(query, doc_key="SOP-004")
        assert current.chunks
        assert {c.revision for c in current.chunks} == {"B"}

        historical = await retriever.retrieve(query, doc_key="SOP-004", as_of=date(2024, 1, 15))
        assert historical.chunks
        assert {c.revision for c in historical.chunks} == {"A"}

        recent = await retriever.retrieve(query, doc_key="SOP-004", as_of=date(2026, 6, 1))
        assert recent.chunks
        assert {c.revision for c in recent.chunks} == {"B"}
    finally:
        await qdrant.close()


async def test_explicit_revision_scope_returns_only_that_revision(ingested_corpus, app_engine):
    """The non-leakage guarantee from Finding 1: a query explicitly scoped to one
    document and one revision returns only that document at that revision — never
    a neighboring document, never a neighboring revision. Rev A is obsolete, so
    pinning it must still reach it (an audit of what Rev A required) without any
    as-of date, which also proves the pin overrides the effective-only default."""
    settings = get_settings()
    providers = build_providers(settings.providers)
    qdrant = make_client(settings.qdrant)
    session_factory = async_sessionmaker(app_engine, expire_on_commit=False)
    try:
        retriever = HybridRetriever(
            settings=settings,
            qdrant=qdrant,
            session_factory=session_factory,
            embeddings=providers.embeddings,
            reranker=providers.rerank,
        )
        query = "corrective and preventive action effectiveness verification"

        rev_a = await retriever.retrieve(query, doc_key="SOP-004", revision="A")
        assert rev_a.chunks
        assert {c.doc_key for c in rev_a.chunks} == {"SOP-004"}  # no neighbor document
        assert {c.revision for c in rev_a.chunks} == {"A"}  # no neighbor revision

        rev_b = await retriever.retrieve(query, doc_key="SOP-004", revision="B")
        assert rev_b.chunks
        assert {c.doc_key for c in rev_b.chunks} == {"SOP-004"}
        assert {c.revision for c in rev_b.chunks} == {"B"}
    finally:
        await qdrant.close()
