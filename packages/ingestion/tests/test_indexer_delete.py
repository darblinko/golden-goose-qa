"""index_chunks retires a re-indexed version by its exact version_id, never by
doc_key+revision. A sibling version that happens to share a revision label must
keep its historical vectors so as-of retrieval can still reach it.

It also upserts the fresh points before retiring the stale ones (excluding the
ids just written), so a crash mid-replacement can never leave searchable
evidence missing."""

from types import SimpleNamespace
from typing import Any

from gg_ingestion.indexer import index_chunks
from gg_ingestion.models import Chunk
from qdrant_client import models


class _FakeEmbeddings:
    dimensions = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class _CaptureClient:
    def __init__(self) -> None:
        self.delete_selector: Any = None
        self.upserted: list[Any] = []
        self.calls: list[str] = []

    async def delete(self, *, collection_name: str, points_selector: Any, wait: bool) -> None:
        self.calls.append("delete")
        self.delete_selector = points_selector

    async def upsert(self, *, collection_name: str, points: list[Any], wait: bool) -> None:
        self.calls.append("upsert")
        self.upserted = points


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


async def test_delete_is_scoped_to_the_exact_version_id():
    client = _CaptureClient()
    settings = SimpleNamespace(collection="gg_chunks")

    n = await index_chunks(
        client,  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        _FakeEmbeddings(),  # type: ignore[arg-type]
        doc_key="SOP-004",
        doc_type="sop",
        title="t",
        revision="A",
        version_id="ver-xyz",
        chunks=[_child("c1"), _child("c2")],
    )

    assert n == 2
    assert len(client.upserted) == 2
    # Fresh points are written before the stale ones are retired.
    assert client.calls == ["upsert", "delete"]
    selector = client.delete_selector
    assert isinstance(selector, models.FilterSelector)
    must = selector.filter.must
    assert isinstance(must, list)
    assert len(must) == 1  # version_id alone — no doc_key, no revision
    cond = must[0]
    assert isinstance(cond, models.FieldCondition)
    assert cond.key == "version_id"
    assert isinstance(cond.match, models.MatchValue)
    assert cond.match.value == "ver-xyz"


async def test_delete_excludes_the_ids_just_upserted():
    """The retirement delete carries a must_not over exactly the child ids just
    written, so the fresh points survive their own re-index and only genuinely
    stale points of this version are removed."""
    client = _CaptureClient()
    settings = SimpleNamespace(collection="gg_chunks")

    await index_chunks(
        client,  # type: ignore[arg-type]
        settings,  # type: ignore[arg-type]
        _FakeEmbeddings(),  # type: ignore[arg-type]
        doc_key="SOP-004",
        doc_type="sop",
        title="t",
        revision="A",
        version_id="ver-xyz",
        chunks=[_child("c1"), _child("c2")],
    )

    must_not = client.delete_selector.filter.must_not
    assert isinstance(must_not, list) and len(must_not) == 1
    has_id = must_not[0]
    assert isinstance(has_id, models.HasIdCondition)
    assert list(has_id.has_id) == ["c1", "c2"]
