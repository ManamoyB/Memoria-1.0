"""Top-level API and root router aggregation."""

from fastapi import APIRouter

from app.api.routes.agent import router as agent_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import root_router
from app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(documents_router)
api_router.include_router(agent_router)

__all__ = ["api_router", "root_router"]
