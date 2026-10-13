"""Cloudflare Worker entry point.

Everything expensive happens here at module scope, which Workers gives a 1-second
startup budget and captures in the deploy-time snapshot. A request then only routes,
runs the handler, and talks to D1 — the free plan allows just 10ms of CPU per request,
and both importing FastAPI (~200ms) and building the app (~100ms) blow that budget if
they happen inside `fetch`.

Bindings only exist per request, so settings are attached on the first one.
"""

import asgi
from workers import WorkerEntrypoint

from app.config import Settings
from app.main import create_app

app = create_app(defer=True)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if app.state.settings is None:
            app.state.settings = Settings.from_workers_env(self.env).validate(on_workers=True)
        return await asgi.fetch(app, request, self.env, self.ctx)
