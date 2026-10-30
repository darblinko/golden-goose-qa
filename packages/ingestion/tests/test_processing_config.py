"""The processing-config hash pins the settings that determine indexed output.

Content-hash idempotency skips re-indexing unchanged bytes. But if the chunking
parameters or the embedding model change, the *same* bytes must be re-chunked and
re-embedded — otherwise the collection keeps vectors built under a configuration
that no longer exists. The hash captures exactly those inputs so a change forces
a rebuild while an unrelated settings edit (an API host, a log level) does not.
"""

from types import SimpleNamespace

from gg_common.settings import ProviderSettings, RetrievalSettings
from gg_ingestion.processing_config import processing_config_hash


def _hash(settings, implementation="VoyageEmbeddingProvider"):
    return processing_config_hash(settings, embedding_implementation=implementation)


def _settings(**overrides):
    retrieval = RetrievalSettings(
        child_chunk_tokens=overrides.get("child_chunk_tokens", 350),
        parent_chunk_tokens=overrides.get("parent_chunk_tokens", 2000),
        max_embed_chars=overrides.get("max_embed_chars", 8000),
    )
    providers = ProviderSettings(
        embedding_provider=overrides.get("embedding_provider", "voyage"),
        embedding_model=overrides.get("embedding_model", "voyage-4-large"),
        embedding_dimensions=overrides.get("embedding_dimensions", 1024),
    )
    return SimpleNamespace(retrieval=retrieval, providers=providers)


def test_hash_is_stable_hex():
    h = _hash(_settings())
    assert h == _hash(_settings())
    assert len(h) == 64
    int(h, 16)  # hex


def test_chunk_size_change_changes_hash():
    assert _hash(_settings()) != _hash(_settings(child_chunk_tokens=400))


def test_embedding_model_change_changes_hash():
    assert _hash(_settings()) != _hash(_settings(embedding_model="voyage-3"))


def test_embedding_dimensions_change_changes_hash():
    assert _hash(_settings()) != _hash(_settings(embedding_dimensions=512))


def test_max_embed_chars_change_changes_hash():
    assert _hash(_settings()) != _hash(_settings(max_embed_chars=4000))


def test_embedding_implementation_change_changes_hash():
    # A keyless run falls back to fake embeddings under the same settings.
    assert _hash(_settings()) != _hash(_settings(), implementation="FakeEmbeddingProvider")
