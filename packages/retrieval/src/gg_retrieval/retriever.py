"""The full retrieval read path: hybrid search → rerank → parent expansion.

Children (small, precise) are searched and reranked; their parents (full
sections from the registry) are what the generator reads. Rerank scores
replace fusion scores so downstream grading sees one comparable scale.
"""

import logging
import time
from datetime import date

from gg_common.acl import access_level_for
from gg_common.costs import cost_stage
from gg_common.providers.base import EmbeddingProvider, RerankProvider
from gg_common.settings import AppSettings
from gg_common.sparse import query_sparse_vector
from gg_common.tracing import set_span_attributes, span
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gg_retrieval.models import ParentContext, RetrievalResult, RetrievedChunk
from gg_retrieval.parents import fetch_parents
from gg_retrieval.search import ANY_STATUS, build_filter, hybrid_search
from gg_retrieval.synonyms import expand_query

_logger = logging.getLogger("gg.retrieval.parents")


class HybridRetriever:
    def __init__(
        self,
        *,
        settings: AppSettings,
        qdrant: AsyncQdrantClient,
        session_factory: async_sessionmaker[AsyncSession],
        embeddings: EmbeddingProvider,
        reranker: RerankProvider,
    ) -> None:
        self.settings = settings
        self.qdrant = qdrant
        self.session_factory = session_factory
        self.embeddings = embeddings
        self.reranker = reranker

    async def retrieve(
        self,
        query: str,
        *,
        doc_type: str | None = None,
        doc_key: str | None = None,
        revision: str | None = None,
        status: str | None = None,
        as_of: date | None = None,
        now: date | None = None,
        top_k: int | None = None,
        allowed_levels: tuple[str, ...] | None = None,
    ) -> RetrievalResult:
        retrieval = self.settings.retrieval
        timings: dict[str, float] = {}
        # An as-of question is about whichever revision was effective then, so
        # the current-only status default must yield to the date filter.
        effective_moment: date | None = None
        if status is None:
            if as_of or revision:
                # as_of targets the revision effective on a date; an explicit
                # revision pins one exact version. Either way the current-only
                # status default must yield — an obsolete pinned or as-of
                # revision is legitimate, exactly-scoped audit evidence.
                status = ANY_STATUS
            else:
                status = retrieval.default_status_filter
                # Bind the default path to the revision in effect right now, not
                # merely whatever still carries the 'effective' label.
                effective_moment = now or date.today()

        # Only the sparse (keyword) channel sees the crosswalk-expanded query, so
        # QSR/ISO dialect differences don't hide documents. The dense embedding
        # and the reranker both keep the original query: expansion must not shift
        # its semantics, nor bias the cross-encoder toward the appended terms.
        expanded = expand_query(query)

        started = time.monotonic()
        with span("retrieve.embed", expanded=expanded != query), cost_stage("retrieve.embed"):
            dense = await self.embeddings.embed_query(query)
            sparse = query_sparse_vector(expanded)
        timings["embed_ms"] = _ms_since(started)

        started = time.monotonic()
        with span("retrieve.search") as search_span:
            points = await hybrid_search(
                self.qdrant,
                self.settings.qdrant,
                retrieval,
                dense_vector=dense,
                sparse_vector=sparse,
                query_filter=build_filter(
                    doc_type=doc_type,
                    doc_key=doc_key,
                    revision=revision,
                    status=status,
                    as_of=as_of,
                    now=effective_moment,
                    allowed_levels=allowed_levels,
                ),
                limit=retrieval.rerank_in,
            )
            set_span_attributes(search_span, candidates=len(points))
        timings["search_ms"] = _ms_since(started)

        candidates = _cap_children_per_parent(
            [_point_to_chunk(p) for p in points], retrieval.max_children_per_parent
        )
        started = time.monotonic()
        with span("retrieve.rerank", candidates=len(candidates)) as rerank_span:
            with cost_stage("retrieve.rerank"):
                reranked = await self._rerank(query, candidates, top_k or retrieval.rerank_out)
                reranked = _apply_score_floor(reranked, retrieval.rerank_min_score)
            set_span_attributes(rerank_span, reranked=len(reranked))
        timings["rerank_ms"] = _ms_since(started)

        started = time.monotonic()
        with span("retrieve.parents") as parents_span:
            parents = await self._expand_parents(reranked, allowed_levels)
            set_span_attributes(parents_span, parents=len(parents))
        timings["parents_ms"] = _ms_since(started)

        trace: dict[str, object] = {
            "candidates": len(points),
            "entered_rerank": len(candidates),
            "reranked": len(reranked),
            "parents": len(parents),
            "expanded": expanded != query,
        }

        return RetrievalResult(
            query=query,
            chunks=tuple(reranked),
            parents=parents,
            timings_ms=timings,
            trace=trace,
        )

    async def _rerank(
        self, query: str, candidates: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        documents = [f"{c.context_header}\n\n{c.text}" for c in candidates]
        results = await self.reranker.rerank(query, documents, top_k=top_k)
        reranked = []
        for result in results:
            chunk = candidates[result.index]
            reranked.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    doc_key=chunk.doc_key,
                    doc_type=chunk.doc_type,
                    title=chunk.title,
                    revision=chunk.revision,
                    section_path=chunk.section_path,
                    text=chunk.text,
                    context_header=chunk.context_header,
                    score=result.score,
                    parent_id=chunk.parent_id,
                    page=chunk.page,
                    version_id=chunk.version_id,
                )
            )
        return reranked

    async def _expand_parents(
        self, chunks: list[RetrievedChunk], allowed_levels: tuple[str, ...] | None
    ) -> tuple[ParentContext, ...]:
        best_scores: dict[str, float] = {}
        best_child_text: dict[str, str] = {}
        ordered_ids: list[str] = []
        child_versions: dict[str, set[str | None]] = {}
        for chunk in chunks:
            if chunk.parent_id is None:
                continue
            child_versions.setdefault(chunk.parent_id, set()).add(chunk.version_id)
            if chunk.parent_id not in best_scores:
                ordered_ids.append(chunk.parent_id)
                best_scores[chunk.parent_id] = chunk.score
                best_child_text[chunk.parent_id] = chunk.text
            elif chunk.score > best_scores[chunk.parent_id]:
                best_scores[chunk.parent_id] = chunk.score
                best_child_text[chunk.parent_id] = chunk.text
        if not ordered_ids:
            return ()

        async with self.session_factory() as session:
            rows = await fetch_parents(session, ordered_ids)

        parents = []
        for parent_id in ordered_ids:
            row = rows.get(parent_id)
            if row is None:
                # Registry and index disagree: surface loudly rather than
                # silently citing a chunk whose parent context is gone.
                raise LookupError(f"parent chunk {parent_id} missing from registry")
            # The parent's identity is re-verified against the registry, never
            # trusted from the child point: a child may only expand to a parent
            # of its own document version, and the parent's own doc_type must
            # be within the caller's access levels.
            if row["version_id"] not in child_versions[parent_id]:
                raise LookupError(
                    f"parent chunk {parent_id} belongs to document version"
                    f" {row['version_id']}, which no citing child matches"
                )
            # Currency boundary: a stale point can pass the Qdrant filter (its
            # payload lags the registry) yet belong to a tombstoned document or a
            # version that never reached 'indexed'. Drop such a parent and alert
            # rather than cite out-of-scope evidence. This is distinct from a
            # status='obsolete' revision, which an as-of query legitimately
            # returns — pipeline_state and deleted_at are always disqualifying.
            deleted = row.get("deleted_at") is not None
            not_indexed = row.get("pipeline_state", "indexed") != "indexed"
            if deleted or not_indexed:
                _logger.warning(
                    "dropping out-of-scope parent from retrieval context",
                    extra={
                        "extra_fields": {
                            "parent_id": parent_id,
                            "doc_key": row["doc_key"],
                            "version_id": row["version_id"],
                            "deleted": deleted,
                            "pipeline_state": row.get("pipeline_state"),
                        }
                    },
                )
                continue
            level = access_level_for(row["doc_type"])
            if allowed_levels is not None and level not in allowed_levels:
                raise PermissionError(
                    f"parent chunk {parent_id} ({row['doc_key']}) is {level},"
                    " outside the caller's allowed access levels"
                )
            parents.append(
                ParentContext(
                    parent_id=parent_id,
                    doc_key=row["doc_key"],
                    doc_type=row["doc_type"],
                    title=row["title"],
                    revision=row["revision"],
                    section_path=row["section_path"],
                    text=row["text"],
                    context_header=row["context_header"],
                    best_child_score=best_scores[parent_id],
                    page=row["page"],
                    version_id=row["version_id"],
                    matched_child_text=best_child_text[parent_id],
                )
            )
        return tuple(parents)


def _cap_children_per_parent(candidates: list[RetrievedChunk], cap: int) -> list[RetrievedChunk]:
    """Keep at most `cap` children per parent, in fusion-rank order (best first),
    so one large document cannot flood the reranker window and starve other
    relevant documents. cap <= 0 disables the cap. Parentless chunks are always
    kept — the cap groups by parent, and they have none."""
    if cap <= 0:
        return candidates
    counts: dict[str, int] = {}
    kept: list[RetrievedChunk] = []
    for chunk in candidates:
        if chunk.parent_id is None:
            kept.append(chunk)
            continue
        seen = counts.get(chunk.parent_id, 0)
        if seen >= cap:
            continue
        counts[chunk.parent_id] = seen + 1
        kept.append(chunk)
    return kept


def _apply_score_floor(chunks: list[RetrievedChunk], min_score: float) -> list[RetrievedChunk]:
    """Drop candidates the reranker scored below the relevance floor. A
    non-positive floor is a no-op (opt-in) so runs with a scoreless fake
    reranker keep every candidate."""
    if min_score <= 0.0:
        return chunks
    return [chunk for chunk in chunks if chunk.score >= min_score]


def _point_to_chunk(point: models.ScoredPoint) -> RetrievedChunk:
    payload = point.payload or {}
    return RetrievedChunk(
        chunk_id=str(point.id),
        doc_key=payload.get("doc_key", ""),
        doc_type=payload.get("doc_type", ""),
        title=payload.get("title", ""),
        revision=payload.get("revision"),
        section_path=payload.get("section_path", ""),
        text=payload.get("text", ""),
        context_header=payload.get("context_header", ""),
        score=float(point.score or 0.0),
        parent_id=payload.get("parent_id"),
        page=payload.get("page"),
        version_id=payload.get("version_id"),
    )


def _ms_since(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 1)
