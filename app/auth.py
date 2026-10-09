"""Sign-in, identity validation, and user/admin dependencies."""

from dataclasses import dataclass
from typing import Annotated, Any

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request

from app.config import ALLOWED_DOMAIN, Settings

GOOGLE_METADATA_URL = "https://accounts.google.com/.well-known/openid-configuration"


class IdentityError(Exception):
    """Raised when an identity is not allowed to sign in."""


class LoginRequired(Exception):
    """Raised by require_user; the app turns it into a redirect to the login page."""


@dataclass(frozen=True)
class User:
    email: str
    name: str
    is_admin: bool


def validate_email(email: str) -> str:
    """Normalize an email and require it to be exactly @berkeley.edu."""
    email = (email or "").strip().lower()
    local, sep, domain = email.rpartition("@")
    if not sep or not local or domain != ALLOWED_DOMAIN:
        raise IdentityError(f"Only @{ALLOWED_DOMAIN} accounts can sign in.")
    return email


def validate_identity(claims: dict[str, Any]) -> tuple[str, str]:
    """Check Google OIDC claims server-side and return (email, name).

    The `hd` parameter on the authorize URL only steers Google's account picker;
    anyone can strip it, so the verified claims are what we trust.
    """
    if claims.get("email_verified") not in (True, "true"):
        raise IdentityError("Your Google account email is not verified.")
    email = validate_email(claims.get("email", ""))
    if claims.get("hd") != ALLOWED_DOMAIN:
        raise IdentityError(f"Sign in with your @{ALLOWED_DOMAIN} Google account.")
    name = (claims.get("name") or "").strip() or email
    return email, name


def make_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def current_user(request: Request) -> User | None:
    data = request.session.get("user")
    if not data:
        return None
    settings = get_settings(request)
    return User(email=data["email"], name=data["name"], is_admin=settings.is_admin(data["email"]))


def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


CurrentUser = Annotated[User, Depends(require_user)]
AdminUser = Annotated[User, Depends(require_admin)]
