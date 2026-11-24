"""FastAPI application: public API, reviewer API and the reviewer console."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    from app.review_ui import ui

    app.include_router(ui)

    # Public check page (no login): paste a link, get the same result card as the extension. The reviewer console
    # stays at /review behind its token.
    web_dir = Path(__file__).parent / "web"
    app.mount("/web/static", StaticFiles(directory=str(web_dir / "static")), name="web-static")

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(web_dir / "index.html", media_type="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-cache"})

    if settings.run_testsites:
        from app.testsites import start_in_thread

        start_in_thread()
    return app


app = create_app()
