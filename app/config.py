"""Application settings, read from environment variables."""

import json
import os
import secrets
from dataclasses import dataclass
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
    database_path: str = "data/tracker.db"
    dev_login: bool = False
    env: str = "development"
    # Cloud Identity service account used to check Google Group membership.
    # Prefer inline JSON for container deployments; otherwise point at a key file.
    google_service_account_json: str = ""
    google_service_account_file: str = ""
    # Membership in this group is required to sign in at all.
    google_users_group: str = ""
    # Membership in this group grants admin rights.
    google_admins_group: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            secret_key=os.environ.get("SECRET_KEY", ""),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            base_url=os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/"),
            database_path=os.environ.get("DATABASE_PATH", "data/tracker.db"),
            dev_login=_truthy(os.environ.get("DEV_LOGIN")),
            env=os.environ.get("ENV", "development").strip().lower(),
            google_service_account_json=os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""),
            google_service_account_file=os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", ""),
            google_users_group=os.environ.get("GOOGLE_USERS_GROUP", "").strip().lower(),
            google_admins_group=os.environ.get("GOOGLE_ADMINS_GROUP", "").strip().lower(),
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
        if not self.dev_login and not (
            self.google_service_account_json or self.google_service_account_file
        ):
            raise ConfigError(
                "GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE is required "
                "unless DEV_LOGIN=1"
            )
        if not self.dev_login and not (self.google_users_group and self.google_admins_group):
            raise ConfigError(
                "GOOGLE_USERS_GROUP and GOOGLE_ADMINS_GROUP are required unless DEV_LOGIN=1"
            )
        if not self.secret_key:
            # Development convenience: sessions won't survive a restart.
            return Settings(**{**self.__dict__, "secret_key": secrets.token_urlsafe(32)})
        return self

    def service_account_info(self) -> dict:
        """Parse the Cloud Identity service-account key, preferring inline JSON.

        Raises ConfigError on missing/invalid configuration so misconfiguration
        is caught at startup (or at the first sign-in in dev) rather than
        surfacing as a confusing Cloud Identity API error.
        """
        if self.google_service_account_json:
            try:
                return json.loads(self.google_service_account_json)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON: {exc}") from exc
        if self.google_service_account_file:
            try:
                with open(self.google_service_account_file, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                raise ConfigError(
                    f"Could not read GOOGLE_SERVICE_ACCOUNT_FILE "
                    f"{self.google_service_account_file!r}: {exc}"
                ) from exc
        raise ConfigError(
            "No Cloud Identity service-account credentials configured "
            "(set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE)."
        )
