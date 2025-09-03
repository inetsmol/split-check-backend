from fastapi import APIRouter

from src.api.v2.endpoints import check, web_ui, auth, avatars, item, profile
from src.config import config

api_v2_router = APIRouter(prefix="/api/v2")


api_v2_router.include_router(auth.router, prefix="/auth", tags=["auth V2"])
api_v2_router.include_router(avatars.router, prefix="/avatars", tags=["avatars V2"])
api_v2_router.include_router(profile.router, prefix="/users", tags=["profiles V2"])
api_v2_router.include_router(check.router, prefix="/checks", tags=["checks V2"])
api_v2_router.include_router(item.router, prefix="/checks", tags=["items V2"])


if config.app.is_development:
    api_v2_router.include_router(web_ui.router, prefix="/webui", tags=["webui V2"])