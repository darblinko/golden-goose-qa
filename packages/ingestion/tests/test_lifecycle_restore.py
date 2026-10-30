"""Reindexing a superseded revision rewrites its points with a fresh payload.
The registry already records it as obsolete, so reconciliation reports no
change; the pipeline must still restore every indexed version's canonical
lifecycle fields onto the search index after each upsert."""

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion.pipeline import IngestionPipeline

_ROWS = [
    SimpleNamespace(
        id="ver-a",
        effective_from=date(2024, 1, 1),
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        status="obsolete",
        effective_to=date(2025, 1, 1),
    ),
    SimpleNamespace(
        id="ver-b",
        effective_from=date(2025, 1, 1),
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        status="effective",
        effective_to=None,
    ),
]


class _Session:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def execute(self, clause: Any, params: Any = None) -> Any:
        sql = str(clause)
        if sql.lstrip().startswith("SELECT"):
            return list(_ROWS)
        self.updates.append(params)
        return None


class _Qdrant:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}

    async def set_payload(self, *, collection_name: str, payload: Any, points: Any, wait: bool):
        version_id = points.must[0].match.value
        self.payloads[version_id] = payload


async def test_reindexed_superseded_revision_gets_its_lifecycle_back():
    qdrant = _Qdrant()
    pipeline = IngestionPipeline(
        settings=cast(Any, SimpleNamespace(qdrant=SimpleNamespace(collection="gg_chunks"))),
        session_factory=cast(Any, None),
        qdrant=cast(Any, qdrant),
        object_store=cast(Any, None),
        embeddings=cast(Any, SimpleNamespace(dimensions=8)),
        ocr=cast(Any, None),
    )
    session = _Session()
    await pipeline._settle_lifecycles(cast(Any, session), "doc-1")

    assert session.updates == []  # the registry rows were already correct
    assert qdrant.payloads["ver-a"] == {
        "status": "obsolete",
        "effective_to": "2025-01-01T00:00:00Z",
    }
    assert qdrant.payloads["ver-b"] == {"status": "effective", "effective_to": None}
