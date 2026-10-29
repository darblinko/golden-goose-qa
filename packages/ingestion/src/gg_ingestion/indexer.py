"""Qdrant collection management and point upserts.

One collection, named dense + sparse vectors. Dense is int8-quantized; sparse
uses Qdrant's IDF modifier over locally computed BM25 term frequencies.
Re-ingestion upserts the fresh points and then retires only this version's stale
points (scoped to the exact version_id, excluding the ids just written), so no
orphaned vectors survive but a crash mid-replacement never leaves searchable
evidence missing. Every other version — including superseded revisions and any
sibling sharing a revision label — stays indexed for as-of (time-travel)
retrieval.
"""

from datetime import date

from gg_common.acl import (
    ACCESS_GENERAL,
    ACCESS_RESTRICTED,
    KNOWN_GENERAL_DOC_TYPES,
    access_level_for,
)
from gg_common.costs import cost_stage
from gg_common.providers.base import EmbeddingProvider
from gg_common.settings import QdrantSettings
from gg_common.sparse import document_sparse_vector
from gg_common.vectors import DENSE_VECTOR, SPARSE_VECTOR
from qdrant_client import AsyncQdrantClient, models

from gg_ingestion.models import Chunk
from gg_ingestion.registry import SupersedePlan

_PAYLOAD_KEYWORD_INDEXES = (
    "doc_key",
    "doc_type",
    "status",
    "chunk_type",
    "revision",
    "version_id",
    "access_level",
)
_PAYLOAD_DATETIME_INDEXES = ("effective_from", "effective_to")


class VectorConfigMismatchError(RuntimeError):
    """An existing collection's vector layout does not match current settings —
    a changed embedding dimension, or a collection predating the named
    dense+sparse layout. Indexing into it would write vectors it cannot serve."""


def make_client(settings: QdrantSettings) -> AsyncQdrantClient:
    api_key = settings.api_key.get_secret_value() if settings.api_key else None
    return AsyncQdrantClient(url=settings.url, api_key=api_key)


async def validate_vector_config(
    client: AsyncQdrantClient, settings: QdrantSettings, *, dimensions: int
) -> None:
    """Fail closed when an existing collection cannot serve the vectors this
    process would write: no named dense vector, a dense size that disagrees with
    the configured embedding dimensions, or a missing named sparse vector."""
    info = await client.get_collection(settings.collection)
    params = info.config.params
    vectors = params.vectors
    dense = vectors.get(DENSE_VECTOR) if isinstance(vectors, dict) else None
    if dense is None:
        raise VectorConfigMismatchError(
            f"collection {settings.collection!r} has no named dense vector "
            f"{DENSE_VECTOR!r}; it predates the named dense+sparse layout. Recreate it."
        )
    if dense.size != dimensions:
        raise VectorConfigMismatchError(
            f"collection {settings.collection!r} dense vector size {dense.size} does not "
            f"match the configured embedding dimensions {dimensions}; the embedding model "
            "changed. Recreate the collection (or restore the model) rather than indexing "
            "mismatched vectors."
        )
    sparse = params.sparse_vectors or {}
    if SPARSE_VECTOR not in sparse:
        raise VectorConfigMismatchError(
            f"collection {settings.collection!r} has no named sparse vector "
            f"{SPARSE_VECTOR!r}; it predates the named dense+sparse layout. Recreate it."
        )


def payload_datetime(value: date | None) -> str | None:
    return f"{value.isoformat()}T00:00:00Z" if value else None


async def ensure_collection(
    client: AsyncQdrantClient, settings: QdrantSettings, *, dimensions: int
) -> None:
    if not await client.collection_exists(settings.collection):
        await client.create_collection(
            collection_name=settings.collection,
            vectors_config={
                DENSE_VECTOR: models.VectorParams(
                    size=dimensions,
                    distance=models.Distance.COSINE,
                    quantization_config=models.ScalarQuantization(
                        scalar=models.ScalarQuantizationConfig(
                            type=models.ScalarType.INT8, always_ram=True
                        )
                    ),
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
    else:
        # An existing collection is reused as-is, so verify it can actually serve
        # the vectors this process writes before any upsert reaches it.
        await validate_vector_config(client, settings, dimensions=dimensions)
    # Payload indexes are ensured even for an existing collection so schema
    # additions reach long-lived environments; recreation is a cheap no-op.
    for field_name in _PAYLOAD_KEYWORD_INDEXES:
        await client.create_payload_index(
            collection_name=settings.collection,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    for field_name in _PAYLOAD_DATETIME_INDEXES:
        await client.create_payload_index(
            collection_name=settings.collection,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.DATETIME,
        )
    await backfill_access_levels(client, settings)


async def backfill_access_levels(client: AsyncQdrantClient, settings: QdrantSettings) -> None:
    """Label points indexed before access_level existed. Content-hash
    idempotency means unchanged documents are never re-indexed, so a
    long-lived collection converges here instead. The retrieval filter is
    fail-closed (unlabeled points match nothing), which protects restricted
    content in the window before this runs — but would also hide general
    content from restricted callers, hence the backfill."""
    unlabeled = models.IsEmptyCondition(is_empty=models.PayloadField(key="access_level"))
    await client.set_payload(
        collection_name=settings.collection,
        payload={"access_level": ACCESS_GENERAL},
        points=models.Filter(
            must=[
                unlabeled,
                models.FieldCondition(
                    key="doc_type", match=models.MatchAny(any=sorted(KNOWN_GENERAL_DOC_TYPES))
                ),
            ]
        ),
        wait=True,
    )
    # Everything still unlabeled — restricted families, unknown types, or
    # points with no doc_type at all — fails closed.
    await client.set_payload(
        collection_name=settings.collection,
        payload={"access_level": ACCESS_RESTRICTED},
        points=models.Filter(must=[unlabeled]),
        wait=True,
    )


def _batches(items: list[Chunk], size: int) -> list[list[Chunk]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _point_for(
    chunk: Chunk, vector: list[float], base_payload: dict[str, object]
) -> models.PointStruct:
    sparse = document_sparse_vector(chunk.embed_text)
    return models.PointStruct(
        id=chunk.chunk_id,
        vector={
            DENSE_VECTOR: vector,
            SPARSE_VECTOR: models.SparseVector(
                indices=list(sparse.indices), values=list(sparse.values)
            ),
        },
        payload={
            **base_payload,
            "chunk_type": chunk.chunk_type,
            "section_path": chunk.section_path,
            "page": chunk.page,
            "parent_id": chunk.parent_id,
            "ordinal": chunk.ordinal,
            "text": chunk.text,
            "context_header": chunk.context_header,
        },
    )


async def index_chunks(
    client: AsyncQdrantClient,
    settings: QdrantSettings,
    embeddings: EmbeddingProvider,
    *,
    doc_key: str,
    doc_type: str,
    title: str,
    revision: str | None,
    version_id: str,
    chunks: list[Chunk],
    status: str = "effective",
    effective_from: date | None = None,
    batch_size: int = 128,
) -> int:
    """Index child chunks (parents live in Postgres). Returns points written.

    Children are embedded and upserted in fixed-size batches so request size and
    peak memory stay bounded regardless of how many chunks a document produces."""
    children = [c for c in chunks if c.chunk_type != "parent"]
    if not children:
        return 0

    base_payload: dict[str, object] = {
        "doc_key": doc_key,
        "doc_type": doc_type,
        "access_level": access_level_for(doc_type),
        "title": title,
        "revision": revision,
        "status": status,
        "version_id": version_id,
        "effective_from": payload_datetime(effective_from),
        "effective_to": None,
    }

    # Upsert every fresh point first — one bounded batch at a time — then retire
    # only this version's *stale* points (those no longer in the current chunk
    # set). Ordering the single destructive step last, and excluding the ids just
    # written, means a crash mid-batch leaves the prior points intact (no evidence
    # gap) and a crash during the trailing delete leaves the index over-inclusive,
    # never missing.
    #
    # The delete stays scoped to this exact version: every other version of the
    # document must survive so as-of queries can still reach it. The pipeline
    # refuses a new version that reuses another version's revision label before
    # indexing (registry.assert_unique_revision), but versions with no revision
    # label may coexist, so doc_key+revision does not identify one version; the
    # immutable version_id is the retirement key.
    written = 0
    for batch in _batches(children, batch_size):
        with cost_stage("ingest.embed"):
            dense = await embeddings.embed_documents([c.embed_text for c in batch])
        points = [
            _point_for(chunk, vector, base_payload)
            for chunk, vector in zip(batch, dense, strict=True)
        ]
        await client.upsert(collection_name=settings.collection, points=points, wait=True)
        written += len(points)

    await client.delete(
        collection_name=settings.collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="version_id", match=models.MatchValue(value=version_id)
                    )
                ],
                must_not=[models.HasIdCondition(has_id=[c.chunk_id for c in children])],
            )
        ),
        wait=True,
    )
    return written


async def apply_supersessions(
    client: AsyncQdrantClient, settings: QdrantSettings, plans: list[SupersedePlan]
) -> None:
    """Propagate revision lifecycle changes onto the indexed points, so the
    default effective-only filter and as-of date filters see the same state
    the registry records."""
    for plan in plans:
        await client.set_payload(
            collection_name=settings.collection,
            payload={
                "status": plan.status,
                "effective_to": payload_datetime(plan.effective_to),
            },
            points=models.Filter(
                must=[
                    models.FieldCondition(
                        key="version_id", match=models.MatchValue(value=plan.version_id)
                    )
                ]
            ),
            wait=True,
        )
