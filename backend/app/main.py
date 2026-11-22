"""FastAPI application: public API, reviewer API and the reviewer console."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import reviewer, router
from app.config import settings
from app.db import migrate


def create_app() -> FastAPI:
    settings.ensure_dirs()
    migrate()
    app = FastAPI(title="Hami API", version="1.0",
                  description="Checks links before someone pays: capture -> sanitize -> analyze -> score.")
    app.add_middleware(
        CORSMiddleware,
        # Chrome extension pages + Expo dev servers; the native mobile app sends no Origin header.
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",
        allow_origins=settings.cors_extra_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Device-Id"],
        allow_credentials=False,
        max_age=3600,
    )
    app.include_router(router)
    app.include_router(reviewer)
    if settings.run_testsites:
        from app.testsites import start_in_thread

        start_in_thread()
    return app


app = create_app()
