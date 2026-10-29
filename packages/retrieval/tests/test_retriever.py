"""Retriever unit tests with a stub Qdrant client and fake providers.

The stub returns fixed fused candidates; the fake reranker (token overlap)
then has to reorder them, and parent expansion has to group children and
preserve rank order. The Qdrant server itself is covered by integration tests.
"""

from datetime import date
from types import SimpleNamespace
from typing import cast

import gg_retrieval.retriever as retriever_mod
import pytest
from gg_common.providers.base import RerankProvider, RerankResult
from gg_common.providers.fakes import FakeEmbeddingProvider, FakeRerankProvider
from gg_common.settings import AppSettings, RetrievalSettings
from gg_retrieval.models import RetrievedChunk
from gg_retrieval.retriever import (
    HybridRetriever,
    _apply_score_floor,
    _cap_children_per_parent,
)
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PARENT_A = "11111111-1111-5111-8111-111111111111"
PARENT_B = "22222222-2222-5222-8222-222222222222"
VERSION_SOP004 = "33333333-3333-5333-8333-333333333333"
VERSION_SOP012 = "44444444-4444-5444-8444-444444444444"

_POINTS = [
    models.ScoredPoint(
        id="aaaaaaaa-0000-5000-8000-000000000001",
        version=0,
        score=0.9,
        payload={
            "doc_key": "SOP-012",
            "doc_type": "sop",
            "title": "Sterilization Process Control",
            "revision": "C",
            "section_path": "3. Procedure",
            "text": "Sterilization loads shall be released by the quality unit.",
            "context_header": "SOP-012 Rev C — Sterilization Process Control (sop)",
            "parent_id": PARENT_B,
            "page": None,
            "version_id": VERSION_SOP012,
        },
    ),
    models.ScoredPoint(
        id="aaaaaaaa-0000-5000-8000-000000000002",
        version=0,
        score=0.8,
        payload={
            "doc_key": "SOP-004",
            "doc_type": "sop",
            "title": "Corrective and Preventive Action",
            "revision": "B",
            "section_path": "3. Procedure",
            "text": "Effectiveness verification requires objective evidence of no recurrence.",
            "context_header": "SOP-004 Rev B — Corrective and Preventive Action (sop)",
            "parent_id": PARENT_A,
            "page": None,
            "version_id": VERSION_SOP004,
        },
    ),
    models.ScoredPoint(
        id="aaaaaaaa-0000-5000-8000-000000000003",
        version=0,
        score=0.7,
        payload={
            "doc_key": "SOP-004",
            "doc_type": "sop",
            "title": "Corrective and Preventive Action",
            "revision": "B",
            "section_path": "4. Records",
            "text": "CAPA effectiveness verification records are retained per SOP-023.",
            "context_header": "SOP-004 Rev B — Corrective and Preventive Action (sop)",
            "parent_id": PARENT_A,
            "page": None,
            "version_id": VERSION_SOP004,
        },
    ),
]

_PARENT_ROWS = {
    PARENT_A: {
        "version_id": VERSION_SOP004,
        "text": "Full CAPA procedure section text with effectiveness verification details.",
        "context_header": "SOP-004 Rev B — Corrective and Preventive Action (sop)",
        "section_path": "3. Procedure",
        "page": None,
        "doc_key": "SOP-004",
        "doc_type": "sop",
        "title": "Corrective and Preventive Action",
        "revision": "B",
    },
    PARENT_B: {
        "version_id": VERSION_SOP012,
        "text": "Full sterilization control section text.",
        "context_header": "SOP-012 Rev C — Sterilization Process Control (sop)",
        "section_path": "3. Procedure",
        "page": None,
        "doc_key": "SOP-012",
        "doc_type": "sop",
        "title": "Sterilization Process Control",
        "revision": "C",
    },
}


class StubQdrant:
    def __init__(self, points):
        self.points = points
        self.calls = []

    async def query_points(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(points=self.points)


class StubSessionFactory:
    def __call__(self):
        return self

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def retriever(monkeypatch):
    async def fake_fetch_parents(session, parent_ids):
        return {pid: _PARENT_ROWS[pid] for pid in parent_ids if pid in _PARENT_ROWS}

    monkeypatch.setattr(retriever_mod, "fetch_parents", fake_fetch_parents)
    return HybridRetriever(
        settings=AppSettings(),
        qdrant=cast(AsyncQdrantClient, StubQdrant(list(_POINTS))),
        session_factory=cast(async_sessionmaker[AsyncSession], StubSessionFactory()),
        embeddings=FakeEmbeddingProvider(),
        reranker=FakeRerankProvider(),
    )


async def test_rerank_reorders_by_relevance(retriever):
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    assert result.chunks
    # the token-overlap reranker must promote the CAPA chunk over the
    # sterilization chunk that fusion ranked first
    assert result.chunks[0].doc_key == "SOP-004"
    assert result.chunks[0].score >= result.chunks[-1].score


async def test_parents_grouped_and_rank_ordered(retriever):
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    parent_ids = [p.parent_id for p in result.parents]
    assert set(parent_ids) == {PARENT_A, PARENT_B}
    assert len(parent_ids) == 2  # two children of PARENT_A collapse into one parent
    assert parent_ids[0] == PARENT_A  # best-ranked child's parent leads
    best = result.parents[0]
    assert best.best_child_score == max(c.score for c in result.chunks)
    assert best.citation == "SOP-004 Rev B, 3. Procedure"


class _RecordingReranker(RerankProvider):
    """Captures the exact query string handed to the cross-encoder."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        self.queries.append(query)
        results = [RerankResult(index=i, score=1.0 - i * 0.01) for i in range(len(documents))]
        return results[:top_k]


async def test_rerank_uses_original_query_not_expanded(monkeypatch):
    # Crosswalk expansion belongs to the lexical (sparse) channel only. The
    # cross-encoder must judge relevance against what the auditor actually
    # asked, not a keyword-stuffed copy, so rerank sees the original query.
    async def fake_fetch_parents(session, parent_ids):
        return {pid: _PARENT_ROWS[pid] for pid in parent_ids if pid in _PARENT_ROWS}

    monkeypatch.setattr(retriever_mod, "fetch_parents", fake_fetch_parents)
    reranker = _RecordingReranker()
    retriever = HybridRetriever(
        settings=AppSettings(),
        qdrant=cast(AsyncQdrantClient, StubQdrant(list(_POINTS))),
        session_factory=cast(async_sessionmaker[AsyncSession], StubSessionFactory()),
        embeddings=FakeEmbeddingProvider(),
        reranker=reranker,
    )
    query = "How are advisory notices initiated?"  # expands via the crosswalk
    await retriever.retrieve(query)
    assert reranker.queries == [query]  # verbatim, no appended crosswalk terms


async def test_result_trace_records_stage_counts(retriever):
    # The trace exposes how many candidates each stage saw, so a thin or empty
    # answer can be diagnosed (too few candidates? all dropped by the floor?)
    # without re-running retrieval.
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    trace = result.trace
    assert trace["candidates"] == 3  # three fused points from the stub
    assert trace["entered_rerank"] == 3  # none dropped by the per-parent cap here
    assert trace["reranked"] == len(result.chunks)
    assert trace["parents"] == len(result.parents)
    assert trace["expanded"] is False  # this query matches no crosswalk phrase


async def test_result_trace_flags_query_expansion(retriever):
    # A query that fires the QSR/ISO crosswalk is flagged as expanded, so a trace
    # reader can tell the sparse channel searched on more than the literal query.
    result = await retriever.retrieve("How are advisory notices initiated?")
    assert result.trace["expanded"] is True


async def test_result_trace_counts_child_cap_drops(monkeypatch):
    async def fake_fetch_parents(session, parent_ids):
        return {pid: _PARENT_ROWS[pid] for pid in parent_ids if pid in _PARENT_ROWS}

    monkeypatch.setattr(retriever_mod, "fetch_parents", fake_fetch_parents)
    retriever = HybridRetriever(
        settings=AppSettings(retrieval=RetrievalSettings(max_children_per_parent=1)),
        qdrant=cast(AsyncQdrantClient, StubQdrant(list(_POINTS))),
        session_factory=cast(async_sessionmaker[AsyncSession], StubSessionFactory()),
        embeddings=FakeEmbeddingProvider(),
        reranker=FakeRerankProvider(),
    )
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    # PARENT_A's two children collapse to one under the cap: 3 candidates in, 2
    # entered the reranker.
    assert result.trace["candidates"] == 3
    assert result.trace["entered_rerank"] == 2


def _field_conditions(flt: models.Filter) -> dict[str, object]:
    return {
        c.key: c.match.value  # type: ignore[union-attr]
        for c in flt.must  # type: ignore[union-attr]
        if isinstance(c, models.FieldCondition)
    }


def _has_effective_window(flt: models.Filter) -> bool:
    """A nested should-clause is the revision-in-effect window (timeless-type OR
    controlled effective interval) that both as-of and default retrieval add."""
    return any(
        isinstance(c, models.Filter) and c.should is not None
        for c in flt.must  # type: ignore[union-attr]
    )


async def test_status_filter_applied_by_default(retriever):
    await retriever.retrieve("any question", now=date(2024, 3, 15))
    call = retriever.qdrant.calls[0]
    for prefetch in call["prefetch"]:
        assert _field_conditions(prefetch.filter) == {"status": "effective"}
        # default retrieval also binds to the revision in effect right now
        assert _has_effective_window(prefetch.filter)


async def test_doc_type_filter_added(retriever):
    await retriever.retrieve("any question", doc_type="capa", now=date(2024, 3, 15))
    call = retriever.qdrant.calls[0]
    assert _field_conditions(call["prefetch"][0].filter) == {
        "doc_type": "capa",
        "status": "effective",
    }


async def test_revision_scope_added_to_filter(retriever):
    await retriever.retrieve("any question", doc_key="SOP-004", revision="A")
    flt = retriever.qdrant.calls[0]["prefetch"][0].filter
    assert _field_conditions(flt) == {"doc_key": "SOP-004", "revision": "A"}
    # An explicit revision pins one exact version regardless of its current
    # lifecycle status, so the status=effective default and the effective-now
    # window must not narrow it — auditing "what did Rev A require?" must reach
    # the obsolete revision, and no neighbor revision can leak in.
    assert not _has_effective_window(flt)


async def test_revision_scope_composes_with_as_of(retriever):
    await retriever.retrieve(
        "any question", doc_key="SOP-004", revision="A", as_of=date(2024, 1, 15)
    )
    flt = retriever.qdrant.calls[0]["prefetch"][0].filter
    fields = _field_conditions(flt)
    assert fields["doc_key"] == "SOP-004"
    assert fields["revision"] == "A"
    assert "status" not in fields
    assert _has_effective_window(flt)  # the as-of window still applies


async def test_as_of_query_drops_status_and_keeps_time_window(retriever):
    # An as-of question is about the revision effective then; the current-only
    # status default must yield to the date window, not stack on top of it.
    await retriever.retrieve("any question", as_of=date(2020, 1, 1))
    flt = retriever.qdrant.calls[0]["prefetch"][0].filter
    assert "status" not in _field_conditions(flt)
    assert _has_effective_window(flt)


async def test_explicit_any_status_skips_effective_window(retriever):
    # Auditing obsolete documents (status=any) must not be narrowed by a
    # now-window — the caller explicitly wants revisions no longer in effect.
    await retriever.retrieve("any question", status="any")
    assert retriever.qdrant.calls[0]["prefetch"][0].filter is None


async def test_missing_parent_raises(retriever, monkeypatch):
    async def empty_fetch(session, parent_ids):
        return {}

    monkeypatch.setattr(retriever_mod, "fetch_parents", empty_fetch)
    with pytest.raises(LookupError, match="missing from registry"):
        await retriever.retrieve("effectiveness verification")


async def test_deleted_document_parent_is_dropped(retriever, monkeypatch):
    # A point for SOP-012 slipped past the Qdrant filter, but the registry now
    # marks its document deleted. That parent must be dropped from context (not
    # cited), while the in-scope SOP-004 parent survives.
    async def fetch_with_deleted(session, parent_ids):
        rows = {pid: dict(_PARENT_ROWS[pid]) for pid in parent_ids if pid in _PARENT_ROWS}
        if PARENT_B in rows:
            rows[PARENT_B]["deleted_at"] = "2024-05-01T00:00:00Z"
        return rows

    monkeypatch.setattr(retriever_mod, "fetch_parents", fetch_with_deleted)
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    parent_ids = {p.parent_id for p in result.parents}
    assert PARENT_B not in parent_ids  # tombstoned document dropped
    assert PARENT_A in parent_ids  # in-scope parent kept


async def test_unindexed_version_parent_is_dropped(retriever, monkeypatch):
    # A version whose pipeline never reached 'indexed' must not be cited even if
    # a stale point survived; only in-scope parents remain.
    async def fetch_with_failed(session, parent_ids):
        rows = {pid: dict(_PARENT_ROWS[pid]) for pid in parent_ids if pid in _PARENT_ROWS}
        if PARENT_B in rows:
            rows[PARENT_B]["pipeline_state"] = "failed"
        return rows

    monkeypatch.setattr(retriever_mod, "fetch_parents", fetch_with_failed)
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    parent_ids = {p.parent_id for p in result.parents}
    assert PARENT_B not in parent_ids  # non-indexed version dropped
    assert PARENT_A in parent_ids


async def test_indexed_undeleted_parent_is_kept(retriever, monkeypatch):
    # The positive contract: an indexed, undeleted parent passes the currency
    # boundary. This pins the exact field names the drop check reads.
    async def fetch_in_scope(session, parent_ids):
        rows = {pid: dict(_PARENT_ROWS[pid]) for pid in parent_ids if pid in _PARENT_ROWS}
        for row in rows.values():
            row["deleted_at"] = None
            row["pipeline_state"] = "indexed"
        return rows

    monkeypatch.setattr(retriever_mod, "fetch_parents", fetch_in_scope)
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    parent_ids = {p.parent_id for p in result.parents}
    assert parent_ids == {PARENT_A, PARENT_B}


async def test_empty_index_returns_empty_result(monkeypatch):
    async def fake_fetch_parents(session, parent_ids):
        raise AssertionError("must not be called for empty candidates")

    monkeypatch.setattr(retriever_mod, "fetch_parents", fake_fetch_parents)
    retriever = HybridRetriever(
        settings=AppSettings(),
        qdrant=cast(AsyncQdrantClient, StubQdrant([])),
        session_factory=cast(async_sessionmaker[AsyncSession], StubSessionFactory()),
        embeddings=FakeEmbeddingProvider(),
        reranker=FakeRerankProvider(),
    )
    result = await retriever.retrieve("anything")
    assert result.is_empty
    assert result.parents == ()


async def test_parent_from_wrong_version_raises(retriever, monkeypatch):
    swapped = {
        pid: {**row, "version_id": "99999999-9999-5999-8999-999999999999"}
        for pid, row in _PARENT_ROWS.items()
    }

    async def swapped_fetch(session, parent_ids):
        return {pid: swapped[pid] for pid in parent_ids}

    monkeypatch.setattr(retriever_mod, "fetch_parents", swapped_fetch)
    with pytest.raises(LookupError, match="no citing child matches"):
        await retriever.retrieve("effectiveness verification")


async def test_parent_outside_allowed_levels_raises(retriever, monkeypatch):
    leaked = {
        pid: {**row, "doc_key": "C-2025-0142", "doc_type": "complaint"}
        for pid, row in _PARENT_ROWS.items()
    }

    async def leaked_fetch(session, parent_ids):
        return {pid: leaked[pid] for pid in parent_ids}

    monkeypatch.setattr(retriever_mod, "fetch_parents", leaked_fetch)
    with pytest.raises(PermissionError, match="restricted"):
        await retriever.retrieve("effectiveness verification", allowed_levels=("general",))


async def test_parent_acl_not_applied_for_privileged_caller(retriever):
    result = await retriever.retrieve("effectiveness verification", allowed_levels=None)
    assert result.parents


async def test_parent_carries_matched_child_text_and_version(retriever):
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    best = result.parents[0]  # PARENT_A leads after rerank
    assert best.parent_id == PARENT_A
    assert best.version_id == VERSION_SOP004
    # the verbatim text of the highest-scoring child that matched this parent,
    # not the parent's own section text
    assert best.matched_child_text == (
        "Effectiveness verification requires objective evidence of no recurrence."
    )
    assert best.matched_child_text != best.text


def _chunk(doc_key: str, parent_id: str | None, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c-{doc_key}-{score}",
        doc_key=doc_key,
        doc_type="sop",
        title="t",
        revision="A",
        section_path="s",
        text="body",
        context_header="h",
        score=score,
        parent_id=parent_id,
    )


def test_cap_children_per_parent_keeps_highest_fusion():
    chunks = [
        _chunk("A", "p1", 0.9),
        _chunk("A", "p1", 0.8),
        _chunk("A", "p1", 0.7),
        _chunk("B", "p2", 0.6),
    ]
    capped = _cap_children_per_parent(chunks, 2)
    assert [c.score for c in capped if c.parent_id == "p1"] == [0.9, 0.8]
    assert len(capped) == 3  # two of p1's three children, plus p2's one


def test_cap_children_zero_disables():
    chunks = [_chunk("A", "p1", 0.9), _chunk("A", "p1", 0.8)]
    assert _cap_children_per_parent(chunks, 0) == chunks


def test_cap_children_keeps_parentless_chunks():
    chunks = [_chunk("A", None, 0.9), _chunk("A", None, 0.8)]
    assert len(_cap_children_per_parent(chunks, 1)) == 2


def test_score_floor_drops_below_threshold():
    chunks = [_chunk("A", "p1", 0.9), _chunk("B", "p2", 0.2)]
    assert [c.doc_key for c in _apply_score_floor(chunks, 0.5)] == ["A"]


def test_score_floor_zero_is_noop():
    chunks = [_chunk("A", "p1", -0.5), _chunk("B", "p2", 0.2)]
    assert _apply_score_floor(chunks, 0.0) == chunks


async def test_child_cap_limits_one_document_footprint(monkeypatch):
    async def fake_fetch_parents(session, parent_ids):
        return {pid: _PARENT_ROWS[pid] for pid in parent_ids if pid in _PARENT_ROWS}

    monkeypatch.setattr(retriever_mod, "fetch_parents", fake_fetch_parents)
    retriever = HybridRetriever(
        settings=AppSettings(retrieval=RetrievalSettings(max_children_per_parent=1)),
        qdrant=cast(AsyncQdrantClient, StubQdrant(list(_POINTS))),
        session_factory=cast(async_sessionmaker[AsyncSession], StubSessionFactory()),
        embeddings=FakeEmbeddingProvider(),
        reranker=FakeRerankProvider(),
    )
    result = await retriever.retrieve(
        "effectiveness verification requires objective evidence of no recurrence"
    )
    # PARENT_A had two children in the index; the cap keeps only its best-fusion
    # child, so SOP-004 contributes a single chunk instead of crowding the window.
    assert sum(1 for c in result.chunks if c.doc_key == "SOP-004") == 1
