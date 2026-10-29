"""Provider interfaces. Vendor SDKs stay behind these seams so model churn is a
config change plus one adapter, never a codebase sweep."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class RerankResult:
    index: int
    score: float


@dataclass(frozen=True)
class OCRPage:
    page_number: int
    text: str
    confidence: float
    warnings: tuple[str, ...] = field(default_factory=tuple)


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str: ...


class EmbeddingProvider(ABC):
    dimensions: int

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]: ...


class RerankProvider(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, documents: list[str], *, top_k: int
    ) -> list[RerankResult]: ...


class OCRProvider(ABC):
    @abstractmethod
    async def ocr_page(self, image_bytes: bytes, *, page_number: int) -> OCRPage: ...
