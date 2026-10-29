"""Liveness, readiness, and the stage-by-stage retrieval health report."""

from typing import Any

from fastapi import APIRouter, Request
from gg_retrieval.health import retrieval_health
from sqlalchemy import text

from goldengoose_api.auth import CurrentUser

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, Any]:
    async with request.app.state.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "using_fake_providers": list(request.app.state.providers.using_fakes),
    }


@router.get("/health/retrieval")
async def health_retrieval(request: Request, user: CurrentUser) -> dict[str, Any]:
    return await retrieval_health(request.app.state.retriever)
