"""Login, OAuth callback, dev login, logout."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.auth import (
    IdentityError,
    current_user,
    get_oauth,
    get_settings,
    validate_email,
    validate_identity,
)
from app.config import ALLOWED_DOMAIN
from app.csrf import verify_csrf
from app.groups import GroupsError, get_client
from app.templating import render
from app.urls import app_path, redirect

log = logging.getLogger(__name__)
router = APIRouter()

NOT_ON_ACCESS_LIST = (
    "Your @berkeley.edu account isn't on the access list for this app. "
    "Ask an admin to add you to the access-list Google Group."
)
SIGN_IN_UNAVAILABLE = "Sign-in is temporarily unavailable. Please try again shortly."


def _sign_in(request: Request, email: str, name: str, is_admin: bool) -> RedirectResponse:
    next_path = request.session.get("next", "/")
    request.session.clear()  # drop any pre-login state, including the old CSRF token
    request.session["user"] = {"email": email, "name": name, "is_admin": is_admin}
    return redirect(request, next_path)


def _check_group_access(request: Request, email: str) -> tuple[bool, str | None]:
    """Check users/admins group membership for `email`.

    Returns (is_admin, error). `error` is set, and sign-in must be refused,
    when the user isn't in the users group or the Cloud Identity API fails.
    """
    settings = get_settings(request)
    client = get_client(settings)
    try:
        if not client.is_member(settings.google_users_group, email):
            return False, NOT_ON_ACCESS_LIST
        is_admin = client.is_member(settings.google_admins_group, email)
    except GroupsError as exc:
        log.error("Cloud Identity group check failed for %s: %s", email, exc)
        return False, SIGN_IN_UNAVAILABLE
    return is_admin, None


@router.get("/login", name="login")
async def login(request: Request):
    if current_user(request):
        return redirect(request, "/")
    return render(request, "login.html")


@router.get("/login/google", name="login_google")
async def login_google(request: Request):
    settings = get_settings(request)
    if settings.dev_login:
        return redirect(request, "/dev-login")
    return await get_oauth(request).google.authorize_redirect(
        request,
        redirect_uri=f"{settings.base_url}/auth/callback",
        hd=ALLOWED_DOMAIN,  # UI hint only; enforced in validate_identity
        prompt="select_account",
    )


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    from authlib.integrations.starlette_client import OAuthError  # see make_oauth

    try:
        token = await get_oauth(request).google.authorize_access_token(request)
    except OAuthError as exc:
        log.warning("OAuth error: %s", exc)
        return render(request, "login.html", status_code=400, error="Sign-in failed. Try again.")
    try:
        email, name = validate_identity(token.get("userinfo") or {})
    except IdentityError as exc:
        return render(request, "login.html", status_code=403, error=str(exc))
    is_admin, error = _check_group_access(request, email)
    if error:
        return render(request, "login.html", status_code=403, error=error)
    return _sign_in(request, email, name, is_admin)


@router.get("/dev-login", name="dev_login")
async def dev_login_form(request: Request):
    if not get_settings(request).dev_login:
        raise HTTPException(status_code=404)
    return render(request, "dev_login.html")


@router.post("/dev-login", dependencies=[Depends(verify_csrf)])
async def dev_login(
    request: Request,
    email: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    admin: Annotated[bool, Form()] = False,
):
    if not get_settings(request).dev_login:
        raise HTTPException(status_code=404)
    try:
        email = validate_email(email)
    except IdentityError as exc:
        return render(request, "dev_login.html", status_code=403, error=str(exc), email=email)
    # Dev login never calls the Cloud Identity API; admin status comes from the checkbox.
    return _sign_in(request, email, name.strip() or email, admin)


@router.post("/logout", name="logout", dependencies=[Depends(verify_csrf)])
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(app_path(request, "/login"), status_code=303)
