"""Cloudflare Worker entry point.

The imports below are deliberately at module scope. Workers gives global scope a
1-second startup budget but only 10ms of CPU per request on the free plan, so
importing FastAPI inside `fetch` blows the per-request budget immediately
(`CpuLimitExceeded`). At module scope the cost is paid once when the isolate starts.

Bindings (D1, vars, secrets) only exist per request, so the app itself is still built
on the first request and then reused for the life of the isolate.
"""

import asgi
from workers import WorkerEntrypoint

from app.config import Settings
from app.main import create_app

_app = None


def _get_app(env):
    global _app
    if _app is None:
        _app = create_app(Settings.from_workers_env(env))
    return _app


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(_get_app(self.env), request, self.env, self.ctx)
