"""A stable hash of the settings that determine a version's indexed output.

Content-hash idempotency skips re-indexing bytes it has already processed. That
is only safe while the *processing configuration* is unchanged: the chunking
parameters decide how the bytes are split, and the embedding provider/model/
dimensions decide the vectors written. Change any of these and the same bytes
must be rebuilt. This captures exactly those inputs — nothing else in settings —
so an unrelated edit (an API host, a log level) never triggers a needless rebuild.
"""

import hashlib
import json
from typing import Any


def processing_config_hash(settings: Any) -> str:
    """SHA-256 over the canonical processing config. `settings` need only expose
    `.retrieval` and `.providers` with the fields read below (the app settings do)."""
    config = {
        "child_chunk_tokens": settings.retrieval.child_chunk_tokens,
        "parent_chunk_tokens": settings.retrieval.parent_chunk_tokens,
        "max_embed_chars": settings.retrieval.max_embed_chars,
        "embedding_provider": settings.providers.embedding_provider,
        "embedding_model": settings.providers.embedding_model,
        "embedding_dimensions": settings.providers.embedding_dimensions,
    }
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
