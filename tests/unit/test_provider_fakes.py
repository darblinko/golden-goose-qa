import math

import pytest
from gg_common.providers.base import ChatMessage
from gg_common.providers.fakes import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeOCRProvider,
    FakeRerankProvider,
)


async def test_embeddings_deterministic_and_normalized():
    provider = FakeEmbeddingProvider(dimensions=64)
    first = await provider.embed_query("design history file")
    second = await provider.embed_query("design history file")
    other = await provider.embed_query("supplier audit")
    assert first == second
    assert first != other
    assert len(first) == 64
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)


async def test_embed_documents_matches_query_embedding():
    provider = FakeEmbeddingProvider(dimensions=32)
    docs = await provider.embed_documents(["a", "b"])
    assert docs[0] == await provider.embed_query("a")
    assert docs[1] == await provider.embed_query("b")


async def test_llm_canned_and_recorded():
    provider = FakeLLMProvider(canned={"CAPA": "canned capa answer"})
    messages = [ChatMessage(role="user", content="What is the CAPA process?")]
    assert await provider.complete(messages) == "canned capa answer"
    fallback = await provider.complete([ChatMessage(role="user", content="unrelated")])
    assert fallback.startswith("FAKE_COMPLETION:")
    assert len(provider.calls) == 2


async def test_rerank_orders_by_overlap():
    provider = FakeRerankProvider()
    results = await provider.rerank(
        "sterilization validation report",
        ["annual picnic minutes", "sterilization validation report rev C", "budget"],
        top_k=2,
    )
    assert results[0].index == 1
    assert results[0].score > results[1].score
    assert len(results) == 2


async def test_ocr_deterministic_with_confidence():
    provider = FakeOCRProvider(confidence=0.42)
    page = await provider.ocr_page(b"scanned-bytes", page_number=3)
    again = await provider.ocr_page(b"scanned-bytes", page_number=3)
    assert page == again
    assert page.page_number == 3
    assert page.confidence == pytest.approx(0.42)
    assert page.text.startswith("FAKE_OCR_PAGE:")
