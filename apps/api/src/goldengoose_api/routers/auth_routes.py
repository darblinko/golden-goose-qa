"""Dev token minting. Registered only when environment is local or ci; cloud
environments authenticate through the web app's auth provider instead."""

from fastapi import APIRouter, Request

from goldengoose_api.auth import mint_dev_token
from goldengoose_api.schemas import DevTokenRequest, DevTokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-token", response_model=DevTokenResponse)
async def dev_token(request: Request, body: DevTokenRequest) -> DevTokenResponse:
    settings = request.app.state.settings
    return DevTokenResponse(token=mint_dev_token(settings, email=body.email, role=body.role))
