"""ensure_collection validates an existing collection's vector layout.

Creating the collection is idempotent — an existing one is left in place. But if
the embedding model changed (different dimensions) or the collection predates the
named dense+sparse layout, silently reusing it would index vectors the collection
cannot serve. The startup check fails loudly instead, naming the fix.
"""

from types import SimpleNamespace
from typing import Any, cast

import pytest
from gg_common.settings import QdrantSettings
from gg_common.vectors import DENSE_VECTOR, SPARSE_VECTOR
from gg_ingestion.indexer import VectorConfigMismatchError, validate_vector_config


def _client(*, vectors: Any, sparse: Any) -> Any:
    info = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=vectors, sparse_vectors=sparse))
    )

    async def get_collection(name: str) -> Any:
        return info

    return SimpleNamespace(get_collection=get_collection)


_SETTINGS = QdrantSettings(collection="gg_chunks")


async def test_matching_layout_passes():
    client = _client(
        vectors={DENSE_VECTOR: SimpleNamespace(size=1024)},
        sparse={SPARSE_VECTOR: SimpleNamespace()},
    )
    await validate_vector_config(cast(Any, client), _SETTINGS, dimensions=1024)


async def test_wrong_dimensions_raise():
    client = _client(
        vectors={DENSE_VECTOR: SimpleNamespace(size=512)},
        sparse={SPARSE_VECTOR: SimpleNamespace()},
    )
    with pytest.raises(VectorConfigMismatchError, match="dimensions"):
        await validate_vector_config(cast(Any, client), _SETTINGS, dimensions=1024)


async def test_missing_named_dense_vector_raises():
    # An unnamed-vector collection (single VectorParams, not a dict) predates the
    # named dense+sparse layout.
    client = _client(vectors=SimpleNamespace(size=1024), sparse={SPARSE_VECTOR: SimpleNamespace()})
    with pytest.raises(VectorConfigMismatchError, match="dense"):
        await validate_vector_config(cast(Any, client), _SETTINGS, dimensions=1024)


async def test_missing_sparse_vector_raises():
    client = _client(vectors={DENSE_VECTOR: SimpleNamespace(size=1024)}, sparse={})
    with pytest.raises(VectorConfigMismatchError, match="sparse"):
        await validate_vector_config(cast(Any, client), _SETTINGS, dimensions=1024)
