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


class DeferredSessionMiddleware(SessionMiddleware):
    """SessionMiddleware whose key comes from settings at request time.

    On Workers the app is built at module scope (so it lands in the deploy-time
    snapshot) but secrets only arrive per request, so the signer can't be built in
    `__init__` the way Starlette does it.
    """

    def __init__(self, app, **kwargs):
        super().__init__(app, secret_key="unconfigured", **kwargs)
        self._configured = False

    async def __call__(self, scope, receive, send):
        if not self._configured and scope["type"] in ("http", "websocket"):
            import itsdangerous

            settings = scope["app"].state.settings
            if settings is None:
                raise RuntimeError("app.state.settings must be set before handling requests")
            self.signer = itsdangerous.TimestampSigner(str(settings.secret_key))
            self.path = settings.root_path or "/"
            if settings.https:
                self.security_flags += "; secure"
            self._configured = True
        await super().__call__(scope, receive, send)


def _local_database(database_path: str):
    from app.db import SqliteDatabase, apply_schema

    path = Path(database_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        apply_schema(str(path), SCHEMA.read_text())
        log.warning("Created a new local database at %s", path)
    return SqliteDatabase(str(path))


def create_app(
    settings: Settings | None = None, database: Database | None = None, *, defer: bool = False
) -> FastAPI:
    """Build the app.

    `defer=True` builds it without settings, for Workers: construction then happens at
    module scope and is captured in the deploy-time snapshot instead of costing CPU on
    the first request of every isolate. The caller must set `app.state.settings` from
    the bindings before the first request.
    """
    if not defer:
        settings = (settings or Settings.from_env()).validate()
        if settings.dev_login:
            log.warning("DEV_LOGIN is enabled: anyone can sign in as any @berkeley.edu address.")

    app = FastAPI(
        title="bTrack",
        # Deferred: BASE_URL isn't known yet. A path prefix is rejected in validate(),
        # so this stays empty on Workers.
        root_path="" if defer else settings.root_path,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    if database is None and settings is not None and settings.database_path:
        # Local uvicorn run: back the app with a SQLite file, creating it if needed.
        database = _local_database(settings.database_path)
    # Still None on Workers: each request wraps its own D1 binding instead.
    app.state.database = database
    # Authlib can't be imported during module evaluation on Workers, so when deferred
    # the OAuth client is built on the first sign-in instead (see auth.get_oauth).
    app.state.oauth = None if defer else make_oauth(settings)

    app.add_middleware(
        DeferredSessionMiddleware,
        session_cookie="btrack_session",
        max_age=14 * 24 * 3600,
        same_site="lax",
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

    # Starlette builds this lazily on the first request; do it now so the cost lands in
    # the startup budget (and the deploy-time snapshot) rather than in a request's 10ms.
    app.middleware_stack = app.build_middleware_stack()
    return app
