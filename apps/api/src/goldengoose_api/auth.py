"""Bearer-token auth. Tokens are HS256 JWTs signed with the shared secret the
web app's auth layer also holds. Local and ci environments may mint dev tokens
through the /auth/dev-token route; other environments must never expose it."""

import time
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from gg_common.settings import AppSettings

ROLES = ("admin", "qa_user", "auditor_readonly")
DEV_TOKEN_TTL_SECONDS = 12 * 3600

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthedUser:
    subject: str
    role: str


def mint_dev_token(settings: AppSettings, *, email: str, role: str = "qa_user") -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    now = int(time.time())
    claims = {
        "sub": email,
        "role": role,
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": now,
        "exp": now + DEV_TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, settings.auth_jwt_secret.get_secret_value(), algorithm="HS256")


def verify_token(settings: AppSettings, token: str) -> AuthedUser:
    try:
        claims = jwt.decode(
            token,
            settings.auth_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            options={"require": ["sub", "exp", "iss", "aud", "role"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc
    # No default role: a token that does not name a known role is rejected,
    # never coerced into qa_user.
    role = claims.get("role")
    if role not in ROLES:
        raise HTTPException(status_code=401, detail="unknown role in token")
    return AuthedUser(subject=str(claims["sub"]), role=role)


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthedUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    settings: AppSettings = request.app.state.settings
    return verify_token(settings, credentials.credentials)


CurrentUser = Annotated[AuthedUser, Depends(current_user)]


async def qa_or_admin(user: CurrentUser) -> AuthedUser:
    """Gate for internal QA surfaces (audit prep). Distinct from document
    ACL: auditor_readonly may chat, but the readiness report is the quality
    team's own gap list and is never served to the audited party's guest."""
    if user.role not in ("admin", "qa_user"):
        raise HTTPException(status_code=403, detail="requires the qa_user or admin role")
    return user


QaOrAdmin = Annotated[AuthedUser, Depends(qa_or_admin)]
