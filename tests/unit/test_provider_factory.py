import pytest
from gg_common.providers.factory import MissingProviderKeyError, build_providers
from gg_common.providers.fakes import FakeEmbeddingProvider, FakeLLMProvider
from gg_common.settings import ProviderSettings
from pydantic import SecretStr


def _settings(**overrides) -> ProviderSettings:
    base = {
        "anthropic_api_key": None,
        "voyage_api_key": None,
        "google_api_key": None,
        "tavily_api_key": None,
    }
    base.update(overrides)
    return ProviderSettings(**base)


def test_all_fakes_when_no_keys():
    providers = build_providers(_settings())
    assert isinstance(providers.llm, FakeLLMProvider)
    assert isinstance(providers.embeddings, FakeEmbeddingProvider)
    assert set(providers.using_fakes) == {"llm", "embeddings", "rerank", "ocr"}


def test_fake_embedding_respects_configured_dimensions():
    providers = build_providers(_settings(embedding_dimensions=256))
    assert providers.embeddings.dimensions == 256


def test_real_llm_selected_when_key_present():
    providers = build_providers(_settings(anthropic_api_key=SecretStr("k")))
    assert "llm" not in providers.using_fakes
    assert type(providers.llm).__name__ == "AnthropicLLMProvider"


def test_require_real_providers_fails_loudly():
    with pytest.raises(MissingProviderKeyError):
        build_providers(_settings(require_real_providers=True))


def test_require_real_rejects_fake_rerank_selection():
    # Every real key is present, but rerank_provider="fake" would still silently
    # substitute a fake under require_real_providers — that must fail loudly.
    settings = _settings(
        require_real_providers=True,
        anthropic_api_key=SecretStr("sk-ant-test"),
        voyage_api_key=SecretStr("pa-test"),
        google_api_key=SecretStr("g-test"),
        rerank_provider="fake",
    )
    with pytest.raises(MissingProviderKeyError):
        build_providers(settings)


def test_require_real_rejects_missing_ocr_key():
    settings = _settings(
        require_real_providers=True,
        anthropic_api_key=SecretStr("sk-ant-test"),
        voyage_api_key=SecretStr("pa-test"),
        google_api_key=None,
    )
    with pytest.raises(MissingProviderKeyError, match="google_api_key"):
        build_providers(settings)
