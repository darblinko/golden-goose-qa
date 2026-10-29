"""SAQ worker exposing the ingestion pipeline as queued tasks.

The queue lives on the existing Postgres (no extra broker). The CLI path and
this worker share IngestionPipeline; the worker exists so ingestion can run
out-of-process from the API and scale independently.

    uv run saq gg_ingestion.worker.settings
"""

from pathlib import Path
from typing import Any

from gg_common.db import create_engine, create_session_factory
from gg_common.objectstore import S3ObjectStore
from gg_common.providers.factory import build_providers
from gg_common.settings import get_settings
from saq import Queue

from gg_ingestion.indexer import make_client
from gg_ingestion.pipeline import IngestionPipeline


def _queue_url() -> str:
    return get_settings().postgres.dsn


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    providers = build_providers(settings.providers)
    store = S3ObjectStore(settings.objectstore)
    store.ensure_bucket(settings.objectstore.bucket_documents)
    store.ensure_bucket(settings.objectstore.bucket_artifacts)
    engine = create_engine(settings.postgres)
    ctx["engine"] = engine
    ctx["qdrant"] = make_client(settings.qdrant)
    ctx["pipeline"] = IngestionPipeline(
        settings=settings,
        session_factory=create_session_factory(engine),
        qdrant=ctx["qdrant"],
        object_store=store,
        embeddings=providers.embeddings,
        ocr=providers.ocr,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["qdrant"].close()
    await ctx["engine"].dispose()


async def ingest_corpus(ctx: dict[str, Any], *, corpus_dir: str) -> dict[str, int]:
    pipeline: IngestionPipeline = ctx["pipeline"]
    report = await pipeline.ingest_corpus(Path(corpus_dir))
    return report.counts()


async def ingest_file(ctx: dict[str, Any], *, path: str, corpus_root: str) -> str:
    pipeline: IngestionPipeline = ctx["pipeline"]
    result = await pipeline.ingest_file(Path(path), corpus_root=Path(corpus_root))
    return result.state


queue = Queue.from_url(_queue_url())

settings = {
    "queue": queue,
    "functions": [ingest_corpus, ingest_file],
    "concurrency": 2,
    "startup": startup,
    "shutdown": shutdown,
}
