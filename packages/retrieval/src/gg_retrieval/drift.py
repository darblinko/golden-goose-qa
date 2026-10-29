"""Registry↔Qdrant drift scan for startup / nightly reconciliation.

An 'indexed' version is never re-processed under content-hash idempotency, so a
point set that diverges from the registry would persist forever with no repair
path. This walks every indexed version, compares its expected child-chunk count
in Postgres against the live point count in Qdrant, and reports the versions that
disagree so an operator (or an automated re-ingest) can repair them.
"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from gg_common.drift import classify_drift
from qdrant_client import AsyncQdrantClient, models
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class VersionDrift:
    version_id: str
    doc_key: str
    expected: int
    actual: int
    kind: str  # "missing" | "mismatch"


_INDEXED_VERSIONS_SQL = text(
    """
    SELECT dv.id AS version_id, d.doc_key AS doc_key,
           count(c.id) FILTER (WHERE c.chunk_type <> 'parent') AS expected
    FROM app.document_versions dv
    JOIN app.documents d ON d.id = dv.document_id
    LEFT JOIN app.chunks c ON c.document_version_id = dv.id
    WHERE dv.pipeline_state = 'indexed'
    GROUP BY dv.id, d.doc_key
    """
)


async def count_version_points(
    qdrant: AsyncQdrantClient, *, collection: str, version_id: str
) -> int:
    result = await qdrant.count(
        collection_name=collection,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(key="version_id", match=models.MatchValue(value=version_id))
            ]
        ),
        exact=True,
    )
    return result.count


async def index_drift(
    qdrant: AsyncQdrantClient,
    session_factory: Callable[[], AsyncSession],
    *,
    collection: str,
) -> dict[str, Any]:
    """Compare each indexed version's expected child count against its live
    Qdrant point count. Returns a summary with the drifted versions listed;
    ``in_sync`` is True only when every indexed version agrees with the index."""
    async with session_factory() as session:
        rows = (await session.execute(_INDEXED_VERSIONS_SQL)).all()

    drifted: list[VersionDrift] = []
    for row in rows:
        version_id = str(row.version_id)
        expected = int(row.expected)
        actual = await count_version_points(qdrant, collection=collection, version_id=version_id)
        kind = classify_drift(expected, actual)
        if kind is not None:
            drifted.append(
                VersionDrift(
                    version_id=version_id,
                    doc_key=str(row.doc_key),
                    expected=expected,
                    actual=actual,
                    kind=kind,
                )
            )
    return {
        "versions_checked": len(rows),
        "in_sync": not drifted,
        "drifted": [asdict(d) for d in drifted],
    }
