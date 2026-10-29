"""Builds the provider set from settings.

Missing keys resolve to deterministic fakes unless require_real_providers is
set, in which case startup fails loudly. A fake is never a silent stand-in in
an environment that demands real inference.
"""

from dataclasses import dataclass

from gg_common.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    OCRProvider,
    RerankProvider,
)
from gg_common.providers.fakes import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeOCRProvider,
    FakeRerankProvider,
)
from gg_common.settings import ProviderSettings


class MissingProviderKeyError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSet:
    llm: LLMProvider
    embeddings: EmbeddingProvider
    rerank: RerankProvider
    ocr: OCRProvider
    using_fakes: tuple[str, ...]


def build_providers(settings: ProviderSettings) -> ProviderSet:
    fakes: list[str] = []

    llm: LLMProvider
    if settings.anthropic_api_key:
        from gg_common.providers.real import AnthropicLLMProvider

        llm = AnthropicLLMProvider(
            settings.anthropic_api_key.get_secret_value(), settings.llm_model
        )
    else:
        _require_absent_ok(settings, "anthropic_api_key")
        llm = FakeLLMProvider()
        fakes.append("llm")

    embeddings: EmbeddingProvider
    if settings.embedding_provider == "voyage" and settings.voyage_api_key:
        from gg_common.providers.real import VoyageEmbeddingProvider

        embeddings = VoyageEmbeddingProvider(
            settings.voyage_api_key.get_secret_value(),
            settings.embedding_model,
            settings.embedding_dimensions,
            max_input_chars=settings.embedding_max_input_chars,
        )
    else:
        _require_absent_ok(settings, "voyage_api_key")
        embeddings = FakeEmbeddingProvider(dimensions=settings.embedding_dimensions)
        fakes.append("embeddings")

    rerank: RerankProvider
    if settings.rerank_provider == "voyage" and settings.voyage_api_key:
        from gg_common.providers.real import VoyageRerankProvider

        rerank = VoyageRerankProvider(
            settings.voyage_api_key.get_secret_value(), settings.rerank_model
        )
    else:
        _require_absent_ok(settings, "voyage_api_key")
        rerank = FakeRerankProvider()
        fakes.append("rerank")

    ocr: OCRProvider
    if settings.ocr_provider == "gemini" and settings.google_api_key:
        from gg_common.providers.real import GeminiOCRProvider

        ocr = GeminiOCRProvider(settings.google_api_key.get_secret_value(), settings.ocr_model)
    else:
        _require_absent_ok(settings, "google_api_key")
        ocr = FakeOCRProvider()
        fakes.append("ocr")

    return ProviderSet(
        llm=llm, embeddings=embeddings, rerank=rerank, ocr=ocr, using_fakes=tuple(fakes)
    )


def _require_absent_ok(settings: ProviderSettings, key_name: str) -> None:
    if settings.require_real_providers:
        raise MissingProviderKeyError(
            f"require_real_providers is set but {key_name} is not configured"
        )
