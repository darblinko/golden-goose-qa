"""index_chunks embeds and upserts in fixed-size batches.

A large document can produce hundreds of child chunks. Embedding them in one
provider call and upserting them in one Qdrant request makes request size and
peak memory scale with document size without bound. Batching caps both: the
embed call and the upsert each see at most batch_size chunks, while the crash-safe
ordering is preserved — every fresh point is upserted before the single trailing
stale-delete runs."""

from types import SimpleNamespace
from typing import Any

from gg_ingestion.indexer import index_chunks
from gg_ingestion.models import Chunk
from qdrant_client import models


class _CountingEmbeddings:
    dimensions = 4

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.batch_sizes.append(len(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class _AccumulatingClient:
    def __init__(self) -> None:
        self.upsert_sizes: list[int] = []
        self.upserted_ids: list[str] = []
        self.delete_selector: Any = None
        self.calls: list[str] = []

    async def upsert(self, *, collection_name: str, points: list[Any], wait: bool) -> None:
        self.calls.append("upsert")
        self.upsert_sizes.append(len(points))
        self.upserted_ids.extend(p.id for p in points)

    async def delete(self, *, collection_name: str, points_selector: Any, wait: bool) -> None:
        self.calls.append("delete")
        self.delete_selector = points_selector


def _child(chunk_id: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        ordinal=0,
        chunk_type="child",
        section_path="s",
        text="corrective action effectiveness verification",
        context_header="SOP-004",
        token_count=4,
    )


async def test_embed_and_upsert_are_batched():
    embeddings = _CountingEmbeddings()
    client = _AccumulatingClient()
    settings = SimpleNamespace(collection="gg_chunks")
    children = [_child(f"c{i}") for i in range(5)]

    n = await index_chunks(
        client,  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        embeddings,  # type: ignore[arg-type]
        doc_key="SOP-004",
        doc_type="sop",
        title="t",
        revision="A",
        version_id="ver-xyz",
        chunks=children,
        batch_size=2,
    )

    assert n == 5
    # Five children in batches of two: 2 + 2 + 1.
    assert embeddings.batch_sizes == [2, 2, 1]
    assert client.upsert_sizes == [2, 2, 1]


async def test_all_upserts_precede_the_single_trailing_delete():
    embeddings = _CountingEmbeddings()
    client = _AccumulatingClient()
    settings = SimpleNamespace(collection="gg_chunks")
    children = [_child(f"c{i}") for i in range(5)]

    await index_chunks(
        client,  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        embeddings,  # type: ignore[arg-type]
        doc_key="SOP-004",
        doc_type="sop",
        title="t",
        revision="A",
        version_id="ver-xyz",
        chunks=children,
        batch_size=2,
    )

    # Every fresh point is written before the one destructive step, so a crash
    # mid-batch leaves the index over-inclusive, never missing evidence.
    assert client.calls == ["upsert", "upsert", "upsert", "delete"]
    # The trailing delete still excludes every id written across all batches.
    must_not = client.delete_selector.filter.must_not
    has_id = must_not[0]
    assert isinstance(has_id, models.HasIdCondition)
    assert list(has_id.has_id) == [f"c{i}" for i in range(5)]
