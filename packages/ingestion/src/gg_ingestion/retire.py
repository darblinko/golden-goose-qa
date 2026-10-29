"""Source retirement: withdraw a deleted source from every projection of it.

When a connector listing drops a source (see connectors/sync.py), the staged
file is removed but its already-ingested vectors, chunks, graph nodes, and
register rows would otherwise linger and stay citable. retire_source_path
closes that gap:

- The vector points for the doc_key are deleted first, so retrieval can no
  longer surface the document even if the database write below fails partway.
- The chunk rows are deleted; parent lookups can no longer reach the text.
- The document is tombstoned (deleted_at stamped) rather than hard-deleted, so
  the audit trail still shows it existed and when it was withdrawn.

The knowledge graph and register warehouse are full rebuilds keyed off
indexed_documents(), which excludes tombstoned documents, so they retire the
source on the next derive.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class RetiredSource:
    doc_key: str
    document_id: str
    version_ids: tuple[str, ...]
    chunks_deleted: int


@dataclass(frozen=True)
class RetirementPlan:
    """How a sync cycle's deletions resolve once the same cycle's re-ingested
    documents are known. A deleted source whose doc_key reappeared under a new
    path is a source-side rename, not a removal: retiring it would tombstone a
    document the same cycle just re-confirmed. Such a path is rebound to where it
    now lives instead; every other deleted path is a genuine removal."""

    retire: tuple[str, ...]
    rebind: tuple[tuple[str, str], ...]


def plan_retirements(
    deleted_bindings: Mapping[str, str | None],
    reingested: Mapping[str, str],
) -> RetirementPlan:
    """Classify each deleted source path. `deleted_bindings` maps a deleted path
    to the doc_key currently bound to it (None when nothing live is bound);
    `reingested` maps a doc_key ingested this cycle to the path it came from. A
    deleted path is a *rename* when its doc_key reappears in `reingested` under a
    different path — retire is skipped and the binding moves to the new path. A
    path reappearing unchanged in place is left alone; everything else is retired."""
    retire: list[str] = []
    rebind: list[tuple[str, str]] = []
    for source_path, doc_key in deleted_bindings.items():
        new_path = reingested.get(doc_key) if doc_key is not None else None
        if new_path is None:
            retire.append(source_path)
        elif new_path != source_path:
            rebind.append((source_path, new_path))
    return RetirementPlan(retire=tuple(retire), rebind=tuple(rebind))


async def retire_source_path(
    session: AsyncSession,
    qdrant: AsyncQdrantClient,
    *,
    source_path: str,
    collection: str,
) -> RetiredSource | None:
    """Retire the live document ingested from source_path. Returns None when no
    non-tombstoned document was ingested from that path (already retired, or
    never ingested), which makes the operation idempotent.

    Vector points are removed before the registry is written so a failure after
    this point leaves the document unreachable rather than half-retired."""
    resolved = (
        await session.execute(
            text(
                """
                SELECT d.id AS document_id, d.doc_key
                FROM app.documents d
                JOIN app.document_versions v ON v.document_id = d.id
                WHERE v.source_path = :source_path AND d.deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"source_path": source_path},
        )
    ).first()
    if resolved is None:
        return None
    document_id = str(resolved.document_id)
    doc_key = resolved.doc_key

    version_rows = (
        await session.execute(
            text("SELECT id FROM app.document_versions WHERE document_id = :document_id"),
            {"document_id": document_id},
        )
    ).all()
    version_ids = tuple(str(row.id) for row in version_rows)

    # Retire the vectors first: every revision's points for this doc_key leave
    # the index before any registry state changes.
    await qdrant.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="doc_key", match=models.MatchValue(value=doc_key))]
            )
        ),
        wait=True,
    )

    chunks_deleted = 0
    for version_id in version_ids:
        result = await session.execute(
            text("DELETE FROM app.chunks WHERE document_version_id = :v"),
            {"v": version_id},
        )
        chunks_deleted += cast("CursorResult[Any]", result).rowcount or 0

    await session.execute(
        text(
            "UPDATE app.documents SET deleted_at = now(), updated_at = now() "
            "WHERE id = :document_id"
        ),
        {"document_id": document_id},
    )
    return RetiredSource(
        doc_key=doc_key,
        document_id=document_id,
        version_ids=version_ids,
        chunks_deleted=chunks_deleted,
    )
