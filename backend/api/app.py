from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..core.config import get_settings
from ..core.events import event_broker
from ..core.logging import configure_logging
from ..data.db import initialize_database
from .routes.events import router as events_router
from .routes.health import router as health_router
from .routes.jobs import router as jobs_router
from .routes.profiles import router as profiles_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_database()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def on_startup() -> None:
        event_broker.attach_loop(asyncio.get_running_loop())

    app.include_router(health_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    app.include_router(profiles_router, prefix="/api")
    app.include_router(events_router, prefix="/api")
    return app
