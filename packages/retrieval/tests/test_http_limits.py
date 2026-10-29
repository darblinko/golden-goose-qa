"""The shared response-size guard: a declared or observed body over the cap is
rejected before it can be fully buffered."""

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from gg_retrieval.tools.http_limits import read_capped_bytes


class _CapExceeded(Exception):
    pass


class _FakeResponse:
    """Just the surface `read_capped_bytes` touches: a headers mapping and a
    chunked async body."""

    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self._chunks = chunks

    async def aiter_bytes(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


async def _read(response: _FakeResponse, max_bytes: int) -> bytes:
    return await read_capped_bytes(
        cast(Any, response), max_bytes=max_bytes, target="GET x", on_exceeded=_CapExceeded
    )


async def test_declared_length_over_cap_fails_before_reading():
    response = _FakeResponse([b"unreached"], headers={"content-length": "999"})
    with pytest.raises(_CapExceeded, match="10-byte cap"):
        await _read(response, 10)


async def test_cap_enforced_across_chunks_without_declared_length():
    response = _FakeResponse([b"x" * 6, b"x" * 6])  # 12 bytes, no content-length header
    with pytest.raises(_CapExceeded):
        await _read(response, 10)


async def test_body_at_or_under_cap_is_returned():
    response = _FakeResponse([b"ab", b"cd"], headers={"content-length": "4"})
    assert await _read(response, 10) == b"abcd"


async def test_non_numeric_declared_length_is_ignored_and_body_still_capped():
    response = _FakeResponse([b"x" * 20], headers={"content-length": "chunked"})
    with pytest.raises(_CapExceeded):
        await _read(response, 10)
