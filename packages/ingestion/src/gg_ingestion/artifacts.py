"""Object-store key for a stage artifact (parse.json, chunks.json, metrics.json).

Namespaced by document key first, then content hash, mirroring the document-bytes
key. Two documents that share identical bytes hash the same; keying on the hash
alone would let the second ingested overwrite the first's artifacts, so the
derivation pass — which reads parse.json back by (doc_key, content_hash) — could
attribute one document's parsed content to the other. The single builder here is
the only place the layout is defined, so the write and read paths cannot diverge.
"""


def artifact_key(doc_key: str, content_hash: str, name: str) -> str:
    return f"{doc_key}/{content_hash}/{name}"
