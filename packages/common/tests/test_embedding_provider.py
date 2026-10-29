"""VoyageEmbeddingProvider preflight contract: an input longer than the
configured character ceiling is rejected before any request, so the model can
never silently truncate a chunk and drop the evidence it carries.

No live key: the hosted call is served by an httpx MockTransport that records
whether a request was sent."""

import httpx
import pytest
from gg_common.providers.real import VoyageEmbeddingProvider


def _provider(captured: list[httpx.Request], *, max_input_chars: int) -> VoyageEmbeddingProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"total_tokens": 5},
            },
        )

    provider = VoyageEmbeddingProvider(
        "test-key", "voyage-4-large", dimensions=3, max_input_chars=max_input_chars
    )
    provider._client = httpx.AsyncClient(
        base_url="https://api.voyageai.com", transport=httpx.MockTransport(handler)
    )
    return provider


async def test_oversized_document_rejected_before_request():
    captured: list[httpx.Request] = []
    provider = _provider(captured, max_input_chars=50)
    with pytest.raises(ValueError, match="character"):
        await provider.embed_documents(["ok text", "x" * 51])
    assert captured == []  # rejected before any request was sent


async def test_oversized_query_rejected_before_request():
    captured: list[httpx.Request] = []
    provider = _provider(captured, max_input_chars=50)
    with pytest.raises(ValueError, match="character"):
        await provider.embed_query("y" * 51)
    assert captured == []


async def test_within_ceiling_reaches_provider():
    captured: list[httpx.Request] = []
    provider = _provider(captured, max_input_chars=50)
    vec = await provider.embed_query("short text")
    assert vec == [0.1, 0.2, 0.3]
    assert len(captured) == 1
