"""App factory. Run with: uvicorn --factory app.main:create_app"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired, make_oauth
from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.migrate import upgrade
from app.routes import admin, auth, boards
from app.templating import render
from app.urls import app_path, redirect, route_path

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = (settings or Settings.from_env()).validate()
    if settings.dev_login:
        log.warning("DEV_LOGIN is enabled: anyone can sign in as any @berkeley.edu address.")

    app = FastAPI(
        title="Lab Board Tracker",
        root_path=settings.root_path,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    upgrade(settings.database_path)  # create/upgrade the schema so a fresh checkout just runs
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_path)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.oauth = make_oauth(settings)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="board_tracker_session",
        max_age=14 * 24 * 3600,
        path=settings.root_path or "/",
        same_site="lax",
        https_only=settings.https,
    )
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, _exc: LoginRequired):
        if request.method == "GET":
            request.session["next"] = route_path(request)
        return redirect(request, "/login")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        messages = {403: "You don't have access to that.", 404: "Page not found."}
        detail = exc.detail if isinstance(exc.detail, str) and exc.status_code != 404 else None
        return render(
            request,
            "error.html",
            status_code=exc.status_code,
            message=detail or messages.get(exc.status_code, "Something went wrong."),
            home=app_path(request, "/"),
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return PlainTextResponse("ok")

    app.include_router(auth.router)
    app.include_router(boards.router)
    app.include_router(admin.router)
    return app
