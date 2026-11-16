"""Application construction and the Uvicorn factory entry point."""

from fastapi import FastAPI

from app.api.router import api_router
from app.api.v1.auth import register_auth_exception_handlers
from app.api.v1.connections import register_connection_exception_handlers
from app.api.v1.gmail import register_gmail_exception_handlers
from app.api.v1.groq import register_provider_exception_handlers
from app.api.v1.runs import register_execution_exception_handlers
from app.api.workflow_dependencies import register_workflow_exception_handlers
from app.core.config import Settings, load_settings
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse, register_exception_handlers
from app.core.lifespan import application_lifespan
from app.core.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct an independent API instance without starting external services."""
    settings = settings if settings is not None else load_settings()
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "AgentFlow API: authentication, versioned workflow drafts "
            "and controlled execution with opt-in background workers and scheduled pure retries."
        ),
        debug=settings.debug,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=application_lifespan,
        responses={
            "default": {
                "model": ErrorResponse,
                "description": "An error occurred; use request_id when investigating.",
                "headers": REQUEST_ID_HEADER,
            }
        },
    )
    application.state.settings = settings
    register_exception_handlers(application)
    register_auth_exception_handlers(application)
    register_workflow_exception_handlers(application)
    register_execution_exception_handlers(application)
    register_connection_exception_handlers(application)
    register_provider_exception_handlers(application)
    register_gmail_exception_handlers(application)
    application.add_middleware(RequestContextMiddleware, environment=settings.environment)
    application.include_router(api_router)
    return application
