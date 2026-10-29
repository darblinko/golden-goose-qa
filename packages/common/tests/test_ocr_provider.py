"""GeminiOCRProvider request-shape contract: an image is sent with the MIME type
detected from its own bytes, not a fixed literal. Embedded PDF scans are often
JPEG, and mislabeling them image/png misdescribes the payload to the provider.

No live key: the hosted call is served by an httpx MockTransport that captures
the outgoing request so its shape and page accounting can be asserted."""

import httpx
import pytest
from gg_common.providers.real import GeminiOCRProvider, _image_mime_type

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 16
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8
_HEIC = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8


class TestImageMimeType:
    def test_detects_common_formats(self):
        assert _image_mime_type(_JPEG) == "image/jpeg"
        assert _image_mime_type(_PNG) == "image/png"
        assert _image_mime_type(_WEBP) == "image/webp"
        assert _image_mime_type(_HEIC) == "image/heic"

    def test_unrecognized_format_fails_closed(self):
        with pytest.raises(ValueError, match="unrecognized image format"):
            _image_mime_type(b"GIF89a" + b"\x00" * 16)


def _provider_with_capture(captured: list[httpx.Request]) -> GeminiOCRProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Line one\nLine two\nCONFIDENCE:0.92"}]}}
                ],
                "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 22},
            },
        )

    provider = GeminiOCRProvider(api_key="test-key", model="gemini-3-flash")
    provider._client = httpx.AsyncClient(
        base_url="https://generativelanguage.googleapis.com",
        transport=httpx.MockTransport(handler),
    )
    return provider


async def test_jpeg_sent_with_jpeg_mime_and_page_preserved():
    captured: list[httpx.Request] = []
    provider = _provider_with_capture(captured)

    page = await provider.ocr_page(_JPEG, page_number=7)

    assert page.page_number == 7
    assert page.text == "Line one\nLine two"
    assert page.confidence == 0.92
    body = _request_json(captured)
    inline = body["contents"][0]["parts"][1]["inline_data"]
    assert inline["mime_type"] == "image/jpeg"


async def test_png_sent_with_png_mime():
    captured: list[httpx.Request] = []
    provider = _provider_with_capture(captured)

    await provider.ocr_page(_PNG, page_number=1)

    inline = _request_json(captured)["contents"][0]["parts"][1]["inline_data"]
    assert inline["mime_type"] == "image/png"


async def test_unsupported_image_never_reaches_provider():
    captured: list[httpx.Request] = []
    provider = _provider_with_capture(captured)

    with pytest.raises(ValueError, match="unrecognized image format"):
        await provider.ocr_page(b"GIF89a" + b"\x00" * 16, page_number=1)
    assert captured == []  # failed closed before any request was sent


def _request_json(captured: list[httpx.Request]) -> dict:
    import json

    assert len(captured) == 1
    return json.loads(captured[0].content)
