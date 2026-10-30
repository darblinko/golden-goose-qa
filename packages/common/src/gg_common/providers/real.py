"""Thin httpx adapters for hosted providers. No vendor SDK dependencies."""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from gg_common.costs import record_usage
from gg_common.providers.base import (
    ChatMessage,
    EmbeddingProvider,
    LLMProvider,
    OCRPage,
    OCRProvider,
    RerankProvider,
    RerankResult,
)

_RETRY = retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    wait=wait_exponential(multiplier=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)


def _raise_for_status(response: httpx.Response) -> None:
    # Retry 429/5xx; fail fast on 4xx client errors.
    if response.status_code == 429 or response.status_code >= 500:
        response.raise_for_status()
    if response.is_error:
        raise RuntimeError(f"provider error {response.status_code}: {response.text[:500]}")


def _image_mime_type(image_bytes: bytes) -> str:
    """The MIME type Gemini needs, detected from the image's own magic bytes.

    Embedded PDF images are commonly JPEG (DCTDecode) — labeling them
    image/png, as a fixed literal did, misdescribes the payload. An unreadable
    or unsupported format fails closed here rather than being sent mislabeled;
    the pipeline records the page as a failed OCR, never as empty evidence.
    """
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[4:8] == b"ftyp" and image_bytes[8:12] in (b"heic", b"heix", b"heif", b"mif1"):
        return "image/heic" if image_bytes[8:12] in (b"heic", b"heix") else "image/heif"
    raise ValueError(
        "unrecognized image format for OCR; expected JPEG, PNG, WebP, or HEIC/HEIF "
        f"(leading bytes: {image_bytes[:8]!r})"
    )


class AnthropicLLMProvider(LLMProvider):
    def __init__(self, api_key: str, default_model: str, timeout: float = 120.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.anthropic.com",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=timeout,
        )
        self.default_model = default_model

    @_RETRY
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        payload: dict[str, Any] = {
            "model": model or self.default_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": m.role, "content": m.content} for m in messages if m.role != "system"
            ],
        }
        if system:
            payload["system"] = system
        response = await self._client.post("/v1/messages", json=payload)
        _raise_for_status(response)
        data = response.json()
        usage = data.get("usage", {})
        record_usage(
            provider="anthropic",
            model=str(payload["model"]),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
        )
        return "".join(b["text"] for b in data["content"] if b["type"] == "text")


class VoyageEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float = 60.0,
        max_input_chars: int = 32000,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.voyageai.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self.model = model
        self.dimensions = dimensions
        self._max_input_chars = max_input_chars

    def _reject_oversized(self, texts: list[str]) -> None:
        """Fail loudly on any input the model would truncate. A token is at least
        one character, so an input within the character ceiling is within the
        model's token context; anything larger is refused rather than sent to be
        silently clipped, which would drop the evidence the tail carries."""
        for index, text in enumerate(texts):
            if len(text) > self._max_input_chars:
                raise ValueError(
                    f"embedding input {index} is {len(text)} characters, over the "
                    f"{self._max_input_chars}-character ceiling; the model would truncate "
                    "it and silently drop evidence, so it is rejected rather than sent"
                )

    @_RETRY
    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        response = await self._client.post(
            "/v1/embeddings",
            json={
                "input": texts,
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dimensions,
            },
        )
        _raise_for_status(response)
        body = response.json()
        record_usage(
            provider="voyage",
            model=self.model,
            input_tokens=int(body.get("usage", {}).get("total_tokens", 0)),
        )
        data = sorted(body["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._reject_oversized(texts)
        return await self._embed(texts, "document")

    async def embed_query(self, text: str) -> list[float]:
        self._reject_oversized([text])
        return (await self._embed([text], "query"))[0]


class VoyageRerankProvider(RerankProvider):
    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://api.voyageai.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self.model = model

    @_RETRY
    async def rerank(self, query: str, documents: list[str], *, top_k: int) -> list[RerankResult]:
        response = await self._client.post(
            "/v1/rerank",
            json={
                "query": query,
                "documents": documents,
                "model": self.model,
                "top_k": top_k,
            },
        )
        _raise_for_status(response)
        body = response.json()
        record_usage(
            provider="voyage",
            model=self.model,
            input_tokens=int(body.get("usage", {}).get("total_tokens", 0)),
        )
        return [RerankResult(index=r["index"], score=r["relevance_score"]) for r in body["data"]]


class GeminiOCRProvider(OCRProvider):
    _PROMPT = (
        "Transcribe this scanned document page exactly. Preserve reading order, "
        "table structure as markdown, and mark illegible regions as [ILLEGIBLE]. "
        "After the transcription, on a final line output CONFIDENCE:<0.0-1.0> "
        "reflecting how much of the page you could read reliably."
    )

    def __init__(self, api_key: str, model: str, timeout: float = 120.0) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://generativelanguage.googleapis.com",
            timeout=timeout,
        )
        self._api_key = api_key
        self.model = model

    @_RETRY
    async def ocr_page(self, image_bytes: bytes, *, page_number: int) -> OCRPage:
        import base64

        mime_type = _image_mime_type(image_bytes)
        response = await self._client.post(
            f"/v1beta/models/{self.model}:generateContent",
            # Header, not the `key` query parameter: request URLs are logged.
            headers={"x-goog-api-key": self._api_key},
            json={
                "contents": [
                    {
                        "parts": [
                            {"text": self._PROMPT},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64.b64encode(image_bytes).decode(),
                                }
                            },
                        ]
                    }
                ]
            },
        )
        _raise_for_status(response)
        body = response.json()
        metadata = body.get("usageMetadata", {})
        record_usage(
            provider="gemini",
            model=self.model,
            input_tokens=int(metadata.get("promptTokenCount", 0)),
            output_tokens=int(metadata.get("candidatesTokenCount", 0)),
        )
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        confidence = 0.0
        warnings: list[str] = []
        lines = text.rstrip().splitlines()
        if lines and lines[-1].startswith("CONFIDENCE:"):
            try:
                confidence = float(lines[-1].split(":", 1)[1].strip())
            except ValueError:
                warnings.append("unparseable confidence line")
            text = "\n".join(lines[:-1])
        else:
            warnings.append("missing confidence line")
        return OCRPage(
            page_number=page_number,
            text=text,
            confidence=confidence,
            warnings=tuple(warnings),
        )
