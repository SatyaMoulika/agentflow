"""Compose the versioned API without putting business logic in routers."""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.connections import router as connections_router
from app.api.v1.gmail import router as gmail_router
from app.api.v1.groq import router as groq_router
from app.api.v1.health import router as health_router
from app.api.v1.node_types import router as node_types_router
from app.api.v1.runs import router as runs_router
from app.api.v1.workflows import router as workflows_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(node_types_router)
api_router.include_router(workflows_router)
api_router.include_router(runs_router)
api_router.include_router(groq_router)
api_router.include_router(connections_router)
api_router.include_router(gmail_router)
