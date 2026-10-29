"""Stage artifacts are namespaced by document key, not by content hash alone.

Two distinct documents that happen to share identical bytes (a shared blank
form, an empty template) hash the same. Keyed on the hash alone, their
parse.json/chunks.json/metrics.json would collide — the second ingested would
overwrite the first, and the derivation pass (which reads parse.json back) would
attribute one document's parsed content to the other. The document-bytes object
key already namespaces by doc_key; the artifact key must do the same, and the
write and read paths must agree by construction.
"""

from types import SimpleNamespace
from typing import Any, cast

from gg_ingestion.artifacts import artifact_key
from gg_ingestion.pipeline import IngestionPipeline

HASH = "a" * 64


def test_artifact_key_namespaces_by_doc_key():
    assert artifact_key("SOP-004", HASH, "parse.json") == f"SOP-004/{HASH}/parse.json"


def test_same_bytes_distinct_doc_keys_get_distinct_artifact_keys():
    one = artifact_key("SOP-004", HASH, "parse.json")
    two = artifact_key("SOP-999", HASH, "parse.json")
    assert one != two


def test_put_artifact_writes_under_doc_key_namespace():
    puts: list[tuple[str, str, bytes]] = []
    store = SimpleNamespace(put=lambda bucket, key, data: puts.append((bucket, key, data)))
    pipeline = IngestionPipeline(
        settings=cast(Any, SimpleNamespace(objectstore=SimpleNamespace(bucket_artifacts="art"))),
        session_factory=cast(Any, None),
        qdrant=cast(Any, None),
        object_store=cast(Any, store),
        embeddings=cast(Any, SimpleNamespace(dimensions=8)),
        ocr=cast(Any, None),
    )

    pipeline._put_artifact("SOP-004", HASH, "parse.json", b"payload")

    assert puts == [("art", f"SOP-004/{HASH}/parse.json", b"payload")]
