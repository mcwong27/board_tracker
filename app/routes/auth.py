"""Login, OAuth callback, dev login, logout."""

import logging
from typing import Annotated

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import IdentityError, current_user, get_settings, validate_email, validate_identity
from app.config import ALLOWED_DOMAIN
from app.csrf import verify_csrf
from app.templating import render
from app.urls import app_path, redirect

log = logging.getLogger(__name__)
router = APIRouter()


def _sign_in(request: Request, email: str, name: str) -> RedirectResponse:
    next_path = request.session.get("next", "/")
    request.session.clear()  # drop any pre-login state, including the old CSRF token
    request.session["user"] = {"email": email, "name": name}
    return redirect(request, next_path)


@router.get("/login", name="login")
def login(request: Request):
    if current_user(request):
        return redirect(request, "/")
    return render(request, "login.html")


@router.get("/login/google", name="login_google")
async def login_google(request: Request):
    settings = get_settings(request)
    if settings.dev_login:
        return redirect(request, "/dev-login")
    return await request.app.state.oauth.google.authorize_redirect(
        request,
        redirect_uri=f"{settings.base_url}/auth/callback",
        hd=ALLOWED_DOMAIN,  # UI hint only; enforced in validate_identity
        prompt="select_account",
    )


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        log.warning("OAuth error: %s", exc)
        return render(request, "login.html", status_code=400, error="Sign-in failed. Try again.")
    try:
        email, name = validate_identity(token.get("userinfo") or {})
    except IdentityError as exc:
        return render(request, "login.html", status_code=403, error=str(exc))
    return _sign_in(request, email, name)


@router.get("/dev-login", name="dev_login")
def dev_login_form(request: Request):
    if not get_settings(request).dev_login:
        raise HTTPException(status_code=404)
    return render(request, "dev_login.html")


@router.post("/dev-login", dependencies=[Depends(verify_csrf)])
def dev_login(
    request: Request,
    email: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
):
    if not get_settings(request).dev_login:
        raise HTTPException(status_code=404)
    try:
        email = validate_email(email)
    except IdentityError as exc:
        return render(request, "dev_login.html", status_code=403, error=str(exc), email=email)
    return _sign_in(request, email, name.strip() or email)


@router.post("/logout", name="logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(app_path(request, "/login"), status_code=303)
