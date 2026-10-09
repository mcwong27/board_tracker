"""Application settings, read from environment variables."""

import os
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlparse

ALLOWED_DOMAIN = "berkeley.edu"


class ConfigError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    secret_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    base_url: str = "http://localhost:8000"
    admin_emails: frozenset[str] = field(default_factory=frozenset)
    database_path: str = "data/tracker.db"
    dev_login: bool = False
    env: str = "development"

    @classmethod
    def from_env(cls) -> "Settings":
        admins = os.environ.get("ADMIN_EMAILS", "")
        return cls(
            secret_key=os.environ.get("SECRET_KEY", ""),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            base_url=os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/"),
            admin_emails=frozenset(e.strip().lower() for e in admins.split(",") if e.strip()),
            database_path=os.environ.get("DATABASE_PATH", "data/tracker.db"),
            dev_login=_truthy(os.environ.get("DEV_LOGIN")),
            env=os.environ.get("ENV", "development").strip().lower(),
        )

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def root_path(self) -> str:
        """Path prefix the app is mounted under, e.g. "/tracker" for https://host/tracker."""
        return urlparse(self.base_url).path.rstrip("/")

    @property
    def https(self) -> bool:
        return urlparse(self.base_url).scheme == "https"

    def validate(self) -> "Settings":
        """Fail fast on unsafe or incomplete config; return settings with defaults filled."""
        if self.dev_login and self.is_production:
            raise ConfigError("DEV_LOGIN must not be enabled when ENV=production")
        if self.is_production and not self.secret_key:
            raise ConfigError("SECRET_KEY is required when ENV=production")
        if not self.dev_login and not (self.google_client_id and self.google_client_secret):
            raise ConfigError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required unless DEV_LOGIN=1"
            )
        if not self.secret_key:
            # Development convenience: sessions won't survive a restart.
            return Settings(**{**self.__dict__, "secret_key": secrets.token_urlsafe(32)})
        return self

    def is_admin(self, email: str) -> bool:
        return email.lower() in self.admin_emails
