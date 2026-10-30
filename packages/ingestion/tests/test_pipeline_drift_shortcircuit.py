"""The content-hash 'unchanged' short-circuit is only taken when the already-
indexed version's Qdrant points still match the registry AND it was indexed under
the current processing configuration. A version whose points drifted (a delete
that outran its upsert, a rebuilt collection), or that was indexed under a since-
changed configuration (chunk sizes, embedding model), must fall through and be
re-indexed instead of being reported unchanged forever."""

from types import SimpleNamespace
from typing import Any, cast

from gg_common.providers.fakes import FakeEmbeddingProvider
from gg_common.providers.real import VoyageEmbeddingProvider
from gg_common.settings import ProviderSettings, RetrievalSettings
from gg_ingestion import registry
from gg_ingestion.models import DocMeta
from gg_ingestion.parsers.router import Route
from gg_ingestion.pipeline import IngestionPipeline
from gg_ingestion.processing_config import processing_config_hash

_SETTINGS = SimpleNamespace(
    qdrant=SimpleNamespace(collection="gg_chunks"),
    objectstore=SimpleNamespace(bucket_documents="documents"),
    retrieval=RetrievalSettings(),
    providers=ProviderSettings(),
)
_CURRENT_CONFIG_HASH = processing_config_hash(
    _SETTINGS, embedding_implementation="FakeEmbeddingProvider"
)


class _FakeResult:
    def __init__(self, obj: Any) -> None:
        self._obj = obj

    def one(self) -> Any:
        return self._obj


class _FakeSession:
    """Answers the reads the short-circuit path makes: the version's
    pipeline_state, its stored processing-config hash, and its registry
    child-chunk count. `stored_config_hash` defaults to the current config so a
    test isolates the point-drift dimension unless it says otherwise."""

    def __init__(
        self, *, child_count: int, stored_config_hash: str | None = _CURRENT_CONFIG_HASH
    ) -> None:
        self._child_count = child_count
        self._stored_config_hash = stored_config_hash

    async def execute(self, clause: Any, params: Any = None) -> _FakeResult:
        sql = str(clause)
        if "processing_config_hash" in sql:
            return _FakeResult(SimpleNamespace(processing_config_hash=self._stored_config_hash))
        if "pipeline_state" in sql:
            return _FakeResult(SimpleNamespace(pipeline_state="indexed"))
        if "count(*)" in sql and "app.chunks" in sql:
            return _FakeResult(SimpleNamespace(n=self._child_count))
        raise AssertionError(f"unexpected SQL: {sql}")


class _FakeQdrant:
    def __init__(self, live_count: int) -> None:
        self._live_count = live_count

    async def count(self, *, collection_name: str, count_filter: Any, exact: bool) -> Any:
        return SimpleNamespace(count=self._live_count)


def _pipeline(live_count: int, embeddings: Any = None) -> IngestionPipeline:
    store = SimpleNamespace(exists=lambda bucket, key: True, put=lambda *a: None)
    return IngestionPipeline(
        settings=cast(Any, _SETTINGS),
        session_factory=cast(Any, None),
        qdrant=cast(Any, _FakeQdrant(live_count)),
        object_store=cast(Any, store),
        embeddings=embeddings or FakeEmbeddingProvider(dimensions=8),
        ocr=cast(Any, None),
    )


def _route() -> Route:
    return Route(
        meta=DocMeta(doc_key="SOP-004", doc_type="sop", title="t", file_format="pdf"),
        parser=cast(Any, object()),  # non-None: not the unsupported path
    )


def _registered() -> registry.RegisteredVersion:
    return registry.RegisteredVersion(
        document_id="doc-1",
        version_id="ver-1",
        content_hash="h",
        doc_key="SOP-004",
        created=False,
    )


async def _short_circuit(pipeline: IngestionPipeline, session: _FakeSession) -> Any:
    return await pipeline._registration_short_circuit(
        cast(Any, session),
        route=_route(),
        rel_path="a/sop.pdf",
        data=b"x",
        object_key="k",
        registered=_registered(),
    )


async def test_unchanged_when_points_match_registry():
    pipeline = _pipeline(live_count=3)
    result = await _short_circuit(pipeline, _FakeSession(child_count=3))
    assert result is not None
    assert result.state == "unchanged"


async def test_falls_through_to_reindex_when_points_are_missing():
    # Registry expects 3 child points; Qdrant has none — do not short-circuit.
    pipeline = _pipeline(live_count=0)
    result = await _short_circuit(pipeline, _FakeSession(child_count=3))
    assert result is None


async def test_falls_through_on_count_mismatch():
    pipeline = _pipeline(live_count=2)
    result = await _short_circuit(pipeline, _FakeSession(child_count=3))
    assert result is None


async def test_falls_through_when_processing_config_changed():
    # Points are in sync, but the version was indexed under a different config —
    # rebuild rather than serve chunks/vectors the current config would not make.
    pipeline = _pipeline(live_count=3)
    session = _FakeSession(child_count=3, stored_config_hash="a-different-hash")
    assert await _short_circuit(pipeline, session) is None


async def test_falls_through_when_config_hash_missing():
    # A version indexed before the config-hash column existed (NULL) cannot be
    # proven to match the current config, so it is rebuilt once.
    pipeline = _pipeline(live_count=3)
    session = _FakeSession(child_count=3, stored_config_hash=None)
    assert await _short_circuit(pipeline, session) is None


async def test_falls_through_when_a_real_embedding_key_replaces_the_fake():
    # The settings are unchanged, but a version indexed with the keyless fake
    # embeddings carries hash vectors that real query embeddings cannot match.
    real = VoyageEmbeddingProvider(api_key="test-only", model="voyage-4-large", dimensions=8)
    try:
        pipeline = _pipeline(live_count=3, embeddings=real)
        assert await _short_circuit(pipeline, _FakeSession(child_count=3)) is None
    finally:
        await real.aclose()
