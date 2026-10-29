"""HTTP seam for external tools: rate limiting, TTL caching, offline fakes.

Every external tool talks through a Fetcher. HttpxFetcher is the live path;
CachingFetcher wraps any fetcher with a per-host minimum interval and a TTL
response cache so audit-time bursts of similar questions do not hammer public
APIs; FakeFetcher serves deterministic synthetic payloads for offline and CI
deployments (the same philosophy as the keyless provider fakes).
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
from gg_common.settings import ExternalToolSettings

from gg_retrieval.tools.http_limits import DEFAULT_MAX_RESPONSE_BYTES, read_capped_bytes


class ExternalFetchError(Exception):
    """An external API could not be reached or answered with an error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MalformedExternalResponseError(ExternalFetchError):
    """An external API answered successfully but the payload does not have
    its documented shape. Raised instead of rendering an empty result, so a
    broken source never masquerades as 'no matching records'."""


def _safe_url(url: str) -> str:
    """Scheme + host + path only. Query strings can carry API keys (openFDA
    sends its key as a param), so they never reach an error message."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def require_list(raw: Any, key: str, source: str) -> list[Any]:
    """Every JSON API used here documents its response as an object carrying
    a list under a known key. Anything else raises rather than quietly
    becoming an empty result."""
    if not isinstance(raw, dict):
        raise MalformedExternalResponseError(f"{source} returned a non-object payload")
    value = raw.get(key)
    if not isinstance(value, list):
        raise MalformedExternalResponseError(f"{source} response has no '{key}' list")
    return value


class Fetcher(ABC):
    @abstractmethod
    async def get_json(self, url: str, params: dict[str, Any]) -> Any: ...

    @abstractmethod
    async def post_json(self, url: str, payload: dict[str, Any]) -> Any: ...


class HttpxFetcher(Fetcher):
    def __init__(
        self,
        timeout_seconds: float = 10.0,
        *,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes

    # Failures are re-raised `from None`: httpx exception strings embed the
    # full request URL including query params, so chaining them would leak
    # credentials into logged tracebacks. Bodies are streamed under a byte cap
    # rather than buffered whole, so a large response cannot exhaust memory.

    async def get_json(self, url: str, params: dict[str, Any]) -> Any:
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("GET", url, params=params) as response,
            ):
                response.raise_for_status()
                body = await read_capped_bytes(
                    response,
                    max_bytes=self._max_bytes,
                    target=f"GET {_safe_url(url)}",
                    on_exceeded=ExternalFetchError,
                )
            return json.loads(body)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ExternalFetchError(
                f"GET {_safe_url(url)} returned status {status}", status_code=status
            ) from None
        except httpx.HTTPError as exc:
            raise ExternalFetchError(f"GET {_safe_url(url)} failed: {type(exc).__name__}") from None
        except ValueError:
            raise MalformedExternalResponseError(
                f"GET {_safe_url(url)} returned a non-JSON body"
            ) from None

    async def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        try:
            async with (
                httpx.AsyncClient(timeout=self._timeout) as client,
                client.stream("POST", url, json=payload) as response,
            ):
                response.raise_for_status()
                body = await read_capped_bytes(
                    response,
                    max_bytes=self._max_bytes,
                    target=f"POST {_safe_url(url)}",
                    on_exceeded=ExternalFetchError,
                )
            return json.loads(body)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise ExternalFetchError(
                f"POST {_safe_url(url)} returned status {status}", status_code=status
            ) from None
        except httpx.HTTPError as exc:
            raise ExternalFetchError(
                f"POST {_safe_url(url)} failed: {type(exc).__name__}"
            ) from None
        except ValueError:
            raise MalformedExternalResponseError(
                f"POST {_safe_url(url)} returned a non-JSON body"
            ) from None


class CachingFetcher(Fetcher):
    """TTL cache + per-host minimum request interval around another fetcher.

    Clock and sleep are injectable so tests can drive time deterministically.
    """

    def __init__(
        self,
        inner: Fetcher,
        *,
        ttl_seconds: float = 3600.0,
        min_interval_seconds: float = 0.25,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._inner = inner
        self._ttl = ttl_seconds
        self._min_interval = min_interval_seconds
        self._time = time_fn
        self._sleep = sleep_fn or asyncio.sleep
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_request_by_host: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}

    async def get_json(self, url: str, params: dict[str, Any]) -> Any:
        return await self._cached("GET", url, params, lambda: self._inner.get_json(url, params))

    async def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        return await self._cached("POST", url, payload, lambda: self._inner.post_json(url, payload))

    def _lock_for(self, host: str) -> asyncio.Lock:
        # No await between get and set, so concurrent coroutines cannot race to
        # create two locks for one host on the single-threaded event loop.
        lock = self._host_locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._host_locks[host] = lock
        return lock

    async def _cached(
        self, method: str, url: str, body: dict[str, Any], call: Callable[[], Awaitable[Any]]
    ) -> Any:
        key = f"{method}\x1e{url}\x1e{json.dumps(body, sort_keys=True, default=str)}"
        hit = self._cache.get(key)
        if hit is not None and hit[0] > self._time():
            return hit[1]
        # Serialize dispatch to a host so the throttle interval is honored across
        # concurrent calls (an uncoordinated read of the last-request time would
        # let a burst fire together and exceed the provider's rate); different
        # hosts still proceed in parallel.
        async with self._lock_for(urlsplit(url).netloc):
            hit = self._cache.get(key)
            if hit is not None and hit[0] > self._time():
                return hit[1]  # populated by a concurrent request while we waited
            await self._throttle(urlsplit(url).netloc)
            payload = await call()
            self._cache[key] = (self._time() + self._ttl, payload)
            return payload

    async def _throttle(self, host: str) -> None:
        last = self._last_request_by_host.get(host)
        now = self._time()
        if last is not None and now - last < self._min_interval:
            await self._sleep(self._min_interval - (now - last))
        self._last_request_by_host[host] = self._time()


class FakeFetcher(Fetcher):
    """Deterministic canned responses keyed by URL substring.

    Payloads are provided by the caller (tests) or by the synthetic defaults
    in fakes.py (offline deployments). Records every request for assertions.
    """

    def __init__(self, responses: tuple[tuple[str, Any], ...]) -> None:
        """responses: (url_substring, payload) pairs; first match wins."""
        self._responses = responses
        self.requests: list[tuple[str, str, dict[str, Any]]] = []

    async def get_json(self, url: str, params: dict[str, Any]) -> Any:
        return self._lookup("GET", url, params)

    async def post_json(self, url: str, payload: dict[str, Any]) -> Any:
        return self._lookup("POST", url, payload)

    def _lookup(self, method: str, url: str, body: dict[str, Any]) -> Any:
        self.requests.append((method, url, body))
        for fragment, payload in self._responses:
            if fragment in url:
                return payload
        raise ExternalFetchError(f"no fake response registered for {url}")


def build_fetcher(settings: ExternalToolSettings) -> Fetcher:
    """The live cached fetcher, or the synthetic offline one when configured."""
    if settings.offline:
        from gg_retrieval.tools.external.fakes import offline_fetcher

        return offline_fetcher()
    return CachingFetcher(
        HttpxFetcher(
            timeout_seconds=settings.timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
        ),
        ttl_seconds=float(settings.cache_ttl_seconds),
        min_interval_seconds=settings.min_interval_ms / 1000.0,
    )
