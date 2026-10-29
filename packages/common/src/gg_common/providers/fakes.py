"""Deterministic fake providers for tests and offline development.

Fakes are honest about being fakes: they never silently stand in when real
providers are required (ProviderSettings.require_real_providers).
"""

import hashlib
import math

from gg_common.costs import estimate_tokens, record_usage
from gg_common.providers.base import (
    ChatMessage,
    EmbeddingProvider,
    LLMProvider,
    OCRPage,
    OCRProvider,
    RerankProvider,
    RerankResult,
)
from gg_common.sparse import tokenize


def _hash_floats(text: str, dimensions: int) -> list[float]:
    """Deterministic pseudo-embedding from content hash, L2-normalized."""
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{text}:{counter}".encode()).digest()
        values.extend(b / 255.0 - 0.5 for b in digest)
        counter += 1
    values = values[:dimensions]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class FakeLLMProvider(LLMProvider):
    def __init__(self, canned: dict[str, str] | None = None) -> None:
        self.canned = canned or {}
        self.calls: list[list[ChatMessage]] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        self.calls.append(messages)
        last = messages[-1].content
        answer = f"FAKE_COMPLETION:{hashlib.sha256(last.encode()).hexdigest()[:12]}"
        for needle, response in self.canned.items():
            if needle in last:
                answer = response
                break
        record_usage(
            provider="fake",
            model="fake-llm",
            input_tokens=sum(estimate_tokens(m.content) for m in messages),
            output_tokens=estimate_tokens(answer),
        )
        return answer


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        record_usage(
            provider="fake",
            model="fake-embedding",
            input_tokens=sum(estimate_tokens(t) for t in texts),
        )
        return [_hash_floats(t, self.dimensions) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        record_usage(provider="fake", model="fake-embedding", input_tokens=estimate_tokens(text))
        return _hash_floats(text, self.dimensions)


class FakeRerankProvider(RerankProvider):
    """Deterministic stand-in for a cross-encoder: IDF-weighted token overlap.

    Tokens come from the same normalizer as the sparse index, and each query
    token is weighted by its rarity across the candidate pool, so one rare
    identifying token (a person name, a part number) outweighs a spread of
    common procedure words — the property a real reranker has and that plain
    set overlap lacks.
    """

    async def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        record_usage(
            provider="fake",
            model="fake-rerank",
            input_tokens=estimate_tokens(query) + sum(estimate_tokens(d) for d in documents),
        )
        query_tokens = frozenset(tokenize(query))
        doc_token_sets = [frozenset(tokenize(doc)) for doc in documents]
        n_docs = len(documents)
        weights = {
            token: math.log(1.0 + n_docs / (1.0 + sum(token in s for s in doc_token_sets)))
            for token in query_tokens
        }
        total = sum(weights.values()) or 1.0
        scored = []
        for i, doc_tokens in enumerate(doc_token_sets):
            score = sum(w for token, w in weights.items() if token in doc_tokens) / total
            scored.append(RerankResult(index=i, score=score))
        scored.sort(key=lambda r: (-r.score, r.index))
        return scored[:top_k]


class FakeOCRProvider(OCRProvider):
    def __init__(self, confidence: float = 0.95) -> None:
        self.confidence = confidence

    async def ocr_page(self, image_bytes: bytes, *, page_number: int) -> OCRPage:
        digest = hashlib.sha256(image_bytes).hexdigest()[:16]
        return OCRPage(
            page_number=page_number,
            text=f"FAKE_OCR_PAGE:{digest}",
            confidence=self.confidence,
        )
