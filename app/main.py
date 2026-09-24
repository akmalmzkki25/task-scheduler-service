"""Application factory: wiring, lifespan, and error handling."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.container import AppContainer
from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.core.clock import Clock
from app.core.config import Settings, get_settings, mask_url
from app.core.logging import configure_logging
from app.domain.errors import DomainError
from app.schemas.common import error_payload
from app.services.seed import seed_demo_data

logger = logging.getLogger("app.api")


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved = settings or get_settings()
        configure_logging(resolved.log_level)
        logger.info(
            "Starting: database=%s redis=%s timezone=%s",
            mask_url(resolved.database_url),
            mask_url(resolved.redis_url),
            resolved.timezone,
        )
        container = AppContainer.build(resolved, clock)
        app.state.container = container
        try:
            if resolved.seed_demo_data:
                await seed_demo_data(container.user_service, container.task_service)
            if resolved.scheduler_enabled:
                container.runner.start()
            yield
        finally:
            await container.aclose()
            logger.info("Stopped")

    app = FastAPI(
        title="Task Scheduler Service",
        description="Runs user-submitted tasks once a day within a per-user daily quota.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(api_router)
    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        logger.info("%s %s -> %s: %s", request.method, request.url.path, exc.code, exc.message)
        return JSONResponse(error_payload(exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'] if p != 'body')}: {err['msg']}"
            for err in exc.errors()
        )
        return JSONResponse(error_payload("VALIDATION_ERROR", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            error_payload(f"HTTP_{exc.status_code}", str(exc.detail)),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # The client gets an ID to quote; the traceback stays in the server log.
        error_id = uuid4().hex[:12]
        logger.exception(
            "Unhandled error %s on %s %s", error_id, request.method, request.url.path
        )
        return JSONResponse(
            error_payload("INTERNAL_ERROR", "An unexpected error occurred", error_id),
            status_code=500,
        )


app = create_app()
