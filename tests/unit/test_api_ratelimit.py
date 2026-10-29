from fastapi.testclient import TestClient
from goldengoose_api.main import create_app
from goldengoose_api.ratelimit import RateLimiter


def test_limiter_blocks_after_max_and_recovers_after_window():
    limiter = RateLimiter(window_seconds=60, max_requests=2)
    assert limiter.allow("a", now=0.0)
    assert limiter.allow("a", now=1.0)
    assert not limiter.allow("a", now=2.0)
    # Other keys are independent.
    assert limiter.allow("b", now=2.0)
    # After the window slides past the first hits, the key recovers.
    assert limiter.allow("a", now=61.5)


def test_middleware_returns_429_but_exempts_health():
    app = create_app()
    app.state.rate_limiter = RateLimiter(window_seconds=60, max_requests=2)
    client = TestClient(app)
    # Unauthenticated 401s still consume the budget.
    assert client.get("/threads").status_code == 401
    assert client.get("/threads").status_code == 401
    assert client.get("/threads").status_code == 429
    assert client.get("/health").status_code == 200
