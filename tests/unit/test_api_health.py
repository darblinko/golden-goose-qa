from fastapi.testclient import TestClient
from gg_common.settings import AppSettings
from goldengoose_api.main import create_app


def test_health_endpoint_no_infrastructure_needed():
    # No `with`: the lifespan (which connects to Postgres/Qdrant) never runs.
    # /health must answer from the process alone.
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_thread_routes_require_auth():
    client = TestClient(create_app())
    assert client.get("/threads").status_code == 401
    assert client.post("/threads", json={"title": "x"}).status_code == 401


def test_garbage_bearer_token_rejected():
    client = TestClient(create_app())
    response = client.get("/threads", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_root_path_prefixes_every_route():
    # One-origin routing: with GG_API_ROOT_PATH=/api the ALB forwards /api/* to
    # this service unstripped, so every route must answer under the prefix and
    # nothing at bare root.
    client = TestClient(create_app(AppSettings(api_root_path="/api")))
    assert client.get("/api/health").status_code == 200
    assert client.get("/health").status_code == 404
    # The thread router moved too — 401 (auth), not 404 (missing route).
    assert client.get("/api/threads").status_code == 401
