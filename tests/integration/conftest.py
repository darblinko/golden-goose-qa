"""Integration fixtures. These tests require the ci compose profile (or CI
service containers) plus an applied migration head; they fail loudly rather
than skip when infrastructure is absent."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from gg_common.graphstore import graph_driver
from gg_common.objectstore import S3ObjectStore
from gg_common.providers.factory import build_providers
from gg_common.settings import get_settings
from gg_ingestion.extract.derive import derive_corpus
from gg_ingestion.extract.graph_migrate import apply_migrations
from gg_ingestion.indexer import make_client
from gg_ingestion.pipeline import IngestionPipeline
from gg_synthdata.cli import cmd_generate
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration

_CYPHER_DIR = Path(__file__).resolve().parents[2] / "infra" / "migrations" / "cypher"


@pytest.fixture
async def app_engine() -> AsyncEngine:
    engine = create_async_engine(get_settings().postgres.sqlalchemy_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def admin_engine() -> AsyncEngine:
    engine = create_async_engine(get_settings().postgres.admin_sqlalchemy_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def corpus_root(tmp_path_factory) -> Path:
    out_dir = tmp_path_factory.mktemp("gg-corpus")
    assert cmd_generate(out_dir, seed=42) == 0
    return out_dir


@pytest.fixture(scope="session")
def ingested_corpus(corpus_root: Path) -> dict[str, Any]:
    """Corpus ingested into live services, once per session. Generation is
    byte-deterministic and ingestion hashes content, so a second run against
    an already-populated stack resolves to `unchanged` rather than re-indexing.
    Synchronous on purpose: it drives its own event loop so session scope does
    not collide with pytest-asyncio's function-scoped loops."""
    report = asyncio.run(_ingest(corpus_root / "corpus"))
    assert not report.failed, [f"{r.path}: {r.reason}" for r in report.failed]
    return {"root": corpus_root, "report": report}


@pytest.fixture(scope="session")
def derived_corpus(ingested_corpus: dict[str, Any]) -> dict[str, Any]:
    """Knowledge graph + register warehouse derived from the ingested corpus,
    once per session. Applies Cypher schema migrations first; derivation is a
    rebuild, so re-running against a populated stack converges to the same
    state. Synchronous for the same loop-scoping reason as ingested_corpus."""
    report = asyncio.run(_derive())
    assert report.graph_loaded
    assert report.register_rows > 0
    return {"report": report}


async def _derive():
    settings = get_settings()
    engine = create_async_engine(settings.postgres.sqlalchemy_url, poolclass=NullPool)
    try:
        async with graph_driver(settings.neo4j) as driver:
            await apply_migrations(driver, _CYPHER_DIR)
            return await derive_corpus(
                settings=settings,
                session_factory=async_sessionmaker(engine, expire_on_commit=False),
                object_store=S3ObjectStore(settings.objectstore),
                graph=driver,
            )
    finally:
        await engine.dispose()


async def _ingest(corpus_dir: Path):
    settings = get_settings()
    providers = build_providers(settings.providers)
    engine = create_async_engine(settings.postgres.sqlalchemy_url, poolclass=NullPool)
    qdrant = make_client(settings.qdrant)
    object_store = S3ObjectStore(settings.objectstore)
    object_store.ensure_bucket(settings.objectstore.bucket_documents)
    object_store.ensure_bucket(settings.objectstore.bucket_artifacts)
    try:
        pipeline = IngestionPipeline(
            settings=settings,
            session_factory=async_sessionmaker(engine, expire_on_commit=False),
            qdrant=qdrant,
            object_store=object_store,
            embeddings=providers.embeddings,
            ocr=providers.ocr,
        )
        return await pipeline.ingest_corpus(corpus_dir)
    finally:
        await qdrant.close()
        await engine.dispose()
