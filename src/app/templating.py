"""Jinja setup and a render helper that injects the current user and CSRF token."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from app.auth import current_user
from app.csrf import csrf_token

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def localtime(value: datetime | None, fmt: str = "%b %-d, %Y %-I:%M %p") -> str:
    """Format a naive-UTC datetime in Berkeley local time."""
    if value is None:
        return ""
    return value.replace(tzinfo=UTC).astimezone(LOCAL_TZ).strftime(fmt)


@pass_context
def path(ctx, p: str) -> str:
    """App-relative path -> browser path (respects a BASE_URL prefix)."""
    return ctx["request"].app.state.settings.root_path + p


templates.env.filters["localtime"] = localtime
templates.env.globals["path"] = path


def render(request: Request, name: str, status_code: int = 200, **context: Any):
    context.update(
        user=current_user(request),
        csrf_token=csrf_token(request),
        dev_login=request.app.state.settings.dev_login,
        flash=request.session.pop("flash", None),
    )
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def flash(request: Request, message: str, kind: str = "ok") -> None:
    """Show a one-time message on the next rendered page."""
    request.session["flash"] = {"message": message, "kind": kind}
