"""Provider adapters release their HTTP connection pools on aclose()."""

from typing import Any

import pytest
from gg_common.providers.factory import ProviderSet, build_providers
from gg_common.providers.real import (
    AnthropicLLMProvider,
    GeminiOCRProvider,
    VoyageEmbeddingProvider,
    VoyageRerankProvider,
)
from gg_common.settings import ProviderSettings


def _real_providers() -> ProviderSet:
    return ProviderSet(
        llm=AnthropicLLMProvider("k", "m"),
        embeddings=VoyageEmbeddingProvider("k", "m", 8),
        rerank=VoyageRerankProvider("k", "m"),
        ocr=GeminiOCRProvider("k", "m"),
        using_fakes=(),
    )


async def test_provider_set_closes_every_real_client():
    providers = _real_providers()
    real: tuple[Any, ...] = (providers.llm, providers.embeddings, providers.rerank, providers.ocr)
    clients = [p._client for p in real]
    assert not any(c.is_closed for c in clients)
    await providers.aclose()
    assert all(c.is_closed for c in clients)


async def test_fakes_close_without_error():
    await build_providers(ProviderSettings()).aclose()


async def test_one_failing_close_does_not_skip_the_rest():
    providers = _real_providers()

    async def broken() -> None:
        raise RuntimeError("close failed")

    providers.llm.aclose = broken  # type: ignore[method-assign]
    with pytest.raises(ExceptionGroup):
        await providers.aclose()
    ocr: Any = providers.ocr
    assert ocr._client.is_closed
