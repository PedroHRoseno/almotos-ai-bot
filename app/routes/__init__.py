from fastapi import APIRouter

from app.routes.chatwoot import router as chatwoot_router
from app.routes.evolution import router as evolution_router
from app.routes.health import router as health_router
from app.routes.webhook import router as webhook_router


def create_api_router() -> APIRouter:
    api = APIRouter()
    api.include_router(health_router)
    api.include_router(webhook_router)
    api.include_router(chatwoot_router)
    api.include_router(evolution_router)
    return api
