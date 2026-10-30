"""Eval entry points close the provider clients they build, including on failure."""

import pytest
from gg_common.settings import get_settings
from gg_evals import battery, cli


class _RecordingProviders:
    def __init__(self) -> None:
        self.closed = 0
        self.embeddings = object()
        self.rerank = object()
        self.llm = object()
        self.using_fakes = ("llm",)

    async def aclose(self) -> None:
        self.closed += 1


class _Closeable:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def close(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


def _failing_retriever(**_kwargs):
    raise RuntimeError("retriever construction failed")


def _stub_construction(monkeypatch, module, providers):
    monkeypatch.setattr(module, "build_providers", lambda _settings: providers)
    monkeypatch.setattr(module, "create_engine", lambda _settings: _Closeable())
    monkeypatch.setattr(module, "create_session_factory", lambda _engine: None)
    monkeypatch.setattr(module, "AsyncQdrantClient", _Closeable)
    monkeypatch.setattr(module, "HybridRetriever", _failing_retriever)


async def test_run_battery_closes_providers_when_evaluation_fails(monkeypatch):
    providers = _RecordingProviders()
    _stub_construction(monkeypatch, battery, providers)
    monkeypatch.setattr(battery, "create_graph_driver", lambda _settings: _Closeable())
    with pytest.raises(RuntimeError):
        await battery.run_battery(get_settings(), [])
    assert providers.closed == 1


async def test_eval_cli_closes_providers_when_evaluation_fails(monkeypatch, tmp_path):
    providers = _RecordingProviders()
    _stub_construction(monkeypatch, cli, providers)
    with pytest.raises(RuntimeError):
        await cli._run(tmp_path / "qa.json", smoke_only=False, gate=0.0, out=None)
    assert providers.closed == 1
