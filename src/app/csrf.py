"""CSRF protection: a per-session token that every POST form must echo back."""

import secrets

from fastapi import HTTPException, Request

SESSION_KEY = "csrf"
FIELD = "csrf_token"


def csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = token
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency for POST routes. Starlette caches the parsed form, so Form() params still work."""
    expected = request.session.get(SESSION_KEY)
    submitted = (await request.form()).get(FIELD)
    if not expected or not isinstance(submitted, str):
        raise HTTPException(status_code=403, detail="Invalid form token. Reload and try again.")
    if not secrets.compare_digest(expected, submitted):
        raise HTTPException(status_code=403, detail="Invalid form token. Reload and try again.")
