import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, billing, health, leases, meters, properties, readings
from app.config import get_settings
from app.db import dispose_engine
from app.errors import install_error_handlers
from app.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    try:
        from app.services.storage import get_storage

        await get_storage().ensure_bucket()
    except Exception as exc:  # storage may come up later; /ready reports it
        get_logger().warning("bucket_init_failed", error=repr(exc))
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Rento API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        get_logger().info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(properties.router)
    app.include_router(leases.router)
    app.include_router(meters.router)
    app.include_router(readings.router)
    app.include_router(billing.router)
    return app


app = create_app()
