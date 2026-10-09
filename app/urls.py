"""URL helpers that respect a BASE_URL path prefix (e.g. https://host/boards)."""

from fastapi import Request
from fastapi.responses import RedirectResponse


def app_path(request: Request, path: str) -> str:
    """Turn an app-relative path like "/boards/3" into the path the browser should use."""
    return request.app.state.settings.root_path + path


def route_path(request: Request) -> str:
    """The current request's app-relative path and query (prefix stripped)."""
    path = request.url.path
    root = request.app.state.settings.root_path
    if root and path.startswith(root):
        path = path[len(root) :] or "/"
    return path + (f"?{request.url.query}" if request.url.query else "")


def safe_next(path: str | None) -> str:
    """Only allow local app paths as post-login destinations."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


def redirect(request: Request, path: str) -> RedirectResponse:
    return RedirectResponse(app_path(request, safe_next(path)), status_code=303)
