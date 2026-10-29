"""Shared response-size guard for the external and internal tool fetchers.

A public API (or a misbehaving internal one) can return an unbounded body; a
fully-buffered parse would let a single large response exhaust worker memory.
Callers stream the response through `read_capped_bytes`, which aborts the moment
the declared or observed size crosses the cap — before the whole body is
resident.
"""

from collections.abc import Callable

import httpx

# Regulatory JSON payloads used here are kilobytes; a few megabytes is a generous
# ceiling that still stops a runaway or hostile response from filling memory.
DEFAULT_MAX_RESPONSE_BYTES = 5_000_000


async def read_capped_bytes(
    response: httpx.Response,
    *,
    max_bytes: int,
    target: str,
    on_exceeded: Callable[[str], Exception],
) -> bytes:
    """Read a streaming response into memory, raising `on_exceeded` the instant
    the body would cross `max_bytes`. A declared Content-Length over the cap
    fails before any body is read; otherwise the cap is enforced chunk by chunk.
    `target` must be a pre-sanitized label (no query string) safe to name in the
    error message."""
    message = f"{target} response exceeds the {max_bytes}-byte cap"
    declared = response.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise on_exceeded(message)
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise on_exceeded(message)
    return bytes(body)
