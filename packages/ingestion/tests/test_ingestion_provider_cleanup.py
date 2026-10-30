"""Entry points close the provider clients they build, including on failure."""

from types import SimpleNamespace

import pytest
from gg_ingestion import cli, worker


class _RecordingProviders:
    def __init__(self) -> None:
        self.closed = 0
        self.embeddings = object()
        self.ocr = object()
        self.using_fakes = ("embeddings",)

    async def aclose(self) -> None:
        self.closed += 1


class _Closeable:
    async def close(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


def _stub_construction(monkeypatch, module, providers):
    monkeypatch.setattr(module, "build_providers", lambda _settings: providers)
    monkeypatch.setattr(module, "create_engine", lambda _settings: _Closeable())
    monkeypatch.setattr(module, "create_session_factory", lambda _engine: None)
    monkeypatch.setattr(module, "make_client", lambda _settings: _Closeable())


async def test_ingest_corpus_closes_providers_when_the_pipeline_fails(monkeypatch, tmp_path):
    providers = _RecordingProviders()
    _stub_construction(monkeypatch, cli, providers)
    monkeypatch.setattr(cli, "_object_store", lambda _settings, _local: None)

    def failing_pipeline(**_kwargs):
        raise RuntimeError("pipeline construction failed")

    monkeypatch.setattr(cli, "IngestionPipeline", failing_pipeline)
    with pytest.raises(RuntimeError):
        await cli._ingest_corpus(tmp_path, None)
    assert providers.closed == 1


async def test_worker_shutdown_closes_the_providers_startup_built(monkeypatch):
    providers = _RecordingProviders()
    _stub_construction(monkeypatch, worker, providers)
    store = SimpleNamespace(ensure_bucket=lambda _bucket: None)
    monkeypatch.setattr(worker, "S3ObjectStore", lambda _settings: store)
    monkeypatch.setattr(worker, "IngestionPipeline", lambda **_kwargs: object())
    ctx: dict = {}
    await worker.startup(ctx)
    await worker.shutdown(ctx)
    assert providers.closed == 1
