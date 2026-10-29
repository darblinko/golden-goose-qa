"""Fixed-window in-memory rate limiter. Suitable for the single-process local
deployment; a shared store (Redis or Postgres) replaces this when the API
scales horizontally in cloud."""

import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 120
_EXEMPT_PATHS = {"/health", "/ready"}


class RateLimiter:
    def __init__(
        self, *, window_seconds: int = WINDOW_SECONDS, max_requests: int = MAX_REQUESTS_PER_WINDOW
    ) -> None:
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        hits = self._hits[key]
        cutoff = current - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(current)
        return True


async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in _EXEMPT_PATHS:
        return await call_next(request)
    limiter: RateLimiter = request.app.state.rate_limiter
    client = request.client.host if request.client else "unknown"
    if not limiter.allow(client):
        return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
    return await call_next(request)
