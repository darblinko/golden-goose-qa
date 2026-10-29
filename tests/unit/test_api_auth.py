import time

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from gg_common.settings import get_settings
from goldengoose_api.auth import mint_dev_token, verify_token
from goldengoose_api.main import create_app


@pytest.fixture()
def settings():
    return get_settings()


def test_mint_and_verify_roundtrip(settings):
    token = mint_dev_token(settings, email="qa@example.com", role="auditor_readonly")
    user = verify_token(settings, token)
    assert user.subject == "qa@example.com"
    assert user.role == "auditor_readonly"


def test_mint_rejects_unknown_role(settings):
    with pytest.raises(ValueError, match="unknown role"):
        mint_dev_token(settings, email="qa@example.com", role="superuser")


def _claims(settings, **overrides):
    claims = {
        "sub": "qa@example.com",
        "role": "qa_user",
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "exp": int(time.time()) + 600,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def test_verify_rejects_wrong_secret(settings):
    forged = jwt.encode(
        _claims(settings, sub="attacker@example.com", role="admin"),
        "wrong-secret-wrong-secret-wrong-secret",
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_token(settings, forged)
    assert excinfo.value.status_code == 401


def test_verify_rejects_expired_token(settings):
    expired = jwt.encode(
        _claims(settings, exp=int(time.time()) - 60),
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_token(settings, expired)
    assert excinfo.value.status_code == 401


def test_verify_rejects_unknown_role_claim(settings):
    token = jwt.encode(
        _claims(settings, role="superuser"),
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_token(settings, token)
    assert excinfo.value.status_code == 401


def test_verify_rejects_missing_role_claim(settings):
    token = jwt.encode(
        _claims(settings, role=None),
        settings.auth_jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        verify_token(settings, token)
    assert excinfo.value.status_code == 401


def test_verify_rejects_missing_or_wrong_audience(settings):
    for aud in (None, "some-other-service"):
        token = jwt.encode(
            _claims(settings, aud=aud),
            settings.auth_jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        with pytest.raises(HTTPException) as excinfo:
            verify_token(settings, token)
        assert excinfo.value.status_code == 401


def test_dev_token_route_mints_verifiable_token(settings):
    client = TestClient(create_app())
    response = client.post("/auth/dev-token", json={"email": "qa@example.com", "role": "qa_user"})
    assert response.status_code == 200
    user = verify_token(settings, response.json()["token"])
    assert user.subject == "qa@example.com"
    assert user.role == "qa_user"
