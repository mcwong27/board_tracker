"""App factory.

On Cloudflare Workers, `src/entry.py` builds the app from the Worker's bindings and
leaves `database` as None so each request wraps the request-scoped D1 binding.
Locally, `uvicorn --factory app.main:create_app` runs the same app against a SQLite
file. Static files are served by the Workers assets binding in production, and by
StaticFiles when running locally.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginRequired, make_oauth
from app.config import Settings
from app.db import Database
from app.routes import admin, assets, auth, fpga
from app.templating import render
from app.urls import app_path, redirect, route_path

log = logging.getLogger(__name__)

PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"
SCHEMA = Path(__file__).resolve().parents[2] / "migrations" / "0001_initial.sql"


def _local_database(database_path: str):
    from app.db import SqliteDatabase, apply_schema

    path = Path(database_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        apply_schema(str(path), SCHEMA.read_text())
        log.warning("Created a new local database at %s", path)
    return SqliteDatabase(str(path))


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = (settings or Settings.from_env()).validate()
    if settings.dev_login:
        log.warning("DEV_LOGIN is enabled: anyone can sign in as any @berkeley.edu address.")

    app = FastAPI(
        title="bTrack",
        root_path=settings.root_path,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    if database is None and settings.database_path:
        # Local uvicorn run: back the app with a SQLite file, creating it if needed.
        database = _local_database(settings.database_path)
    # Still None on Workers: each request wraps its own D1 binding instead.
    app.state.database = database
    app.state.oauth = make_oauth(settings)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="btrack_session",
        max_age=14 * 24 * 3600,
        path=settings.root_path or "/",
        same_site="lax",
        https_only=settings.https,
    )
    if database is not None and PUBLIC_DIR.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=PUBLIC_DIR / "static"), name="static")

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

    # Every handler must be async: Workers has no threads, and FastAPI would
    # otherwise run sync endpoints in a threadpool.
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return PlainTextResponse("ok")

    app.include_router(auth.router)
    app.include_router(assets.router)
    app.include_router(fpga.router)
    app.include_router(admin.router)
    return app
