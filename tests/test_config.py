import pytest

from app.config import ConfigError, Settings


def test_dev_login_refused_in_production():
    with pytest.raises(ConfigError, match="DEV_LOGIN"):
        Settings(dev_login=True, env="production", secret_key="x").validate()


def test_production_requires_secret_key():
    s = Settings(env="production", google_client_id="id", google_client_secret="secret")
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        s.validate()


def test_oauth_credentials_required_without_dev_login():
    with pytest.raises(ConfigError, match="GOOGLE_CLIENT_ID"):
        Settings().validate()


def test_groups_service_account_required_without_dev_login():
    s = Settings(google_client_id="id", google_client_secret="secret")
    with pytest.raises(ConfigError, match="GOOGLE_SERVICE_ACCOUNT"):
        s.validate()


def test_groups_emails_required_without_dev_login():
    s = Settings(
        google_client_id="id",
        google_client_secret="secret",
        google_service_account_json="{}",
    )
    with pytest.raises(ConfigError, match="GOOGLE_USERS_GROUP"):
        s.validate()


def test_dev_settings_get_generated_secret():
    s = Settings(dev_login=True).validate()
    assert len(s.secret_key) > 20


def test_dev_login_skips_groups_config():
    # Groups config is only required when DEV_LOGIN is off.
    Settings(dev_login=True).validate()


def test_from_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_USERS_GROUP", " Users@Berkeley.edu ")
    monkeypatch.setenv("GOOGLE_ADMINS_GROUP", "Admins@berkeley.edu")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", '{"type": "service_account"}')
    monkeypatch.setenv("DEV_LOGIN", "1")
    monkeypatch.setenv("BASE_URL", "https://example.org/assets/")
    s = Settings.from_env()
    assert s.google_users_group == "users@berkeley.edu"
    assert s.google_admins_group == "admins@berkeley.edu"
    assert s.service_account_info() == {"type": "service_account"}
    assert s.dev_login
    assert s.root_path == "/assets"
    assert s.https


def test_service_account_info_requires_json_or_file():
    with pytest.raises(ConfigError, match="service-account"):
        Settings().service_account_info()


def test_service_account_info_rejects_invalid_json():
    with pytest.raises(ConfigError, match="not valid JSON"):
        Settings(google_service_account_json="not json").service_account_info()


def test_workers_settings_read_from_bindings():
    """On Workers, config arrives as a JS-style object of vars and secrets."""

    class FakeEnv:
        ENV = "production"
        BASE_URL = "https://btrack.example.workers.dev/"
        SECRET_KEY = "s3cret"
        GOOGLE_CLIENT_ID = "id"
        GOOGLE_CLIENT_SECRET = "secret"
        GOOGLE_SERVICE_ACCOUNT_JSON = '{"type": "service_account"}'
        GOOGLE_USERS_GROUP = "Users@berkeley.edu"
        GOOGLE_ADMINS_GROUP = "Admins@berkeley.edu"

    settings = Settings.from_workers_env(FakeEnv()).validate()
    assert settings.is_production
    assert settings.base_url == "https://btrack.example.workers.dev"
    assert settings.google_users_group == "users@berkeley.edu"  # normalized
    assert settings.secret_key == "s3cret"


def test_workers_settings_tolerate_missing_bindings():
    class Empty:
        pass

    settings = Settings.from_workers_env(Empty())
    assert settings.secret_key == ""
    assert settings.env == "production"


def test_group_addresses_may_be_on_another_domain():
    """Berkeley's groups are @lists.berkeley.edu, not @berkeley.edu like the users.

    Only the signing-in identity is restricted to ALLOWED_DOMAIN; group addresses are
    config and are never domain-checked.
    """
    settings = Settings(
        dev_login=False,
        secret_key="x",
        google_client_id="id",
        google_client_secret="s",
        google_service_account_json='{"type": "service_account"}',
        google_users_group="btrack-users@lists.berkeley.edu",
        google_admins_group="btrack-admins@lists.berkeley.edu",
    ).validate()
    assert settings.google_users_group == "btrack-users@lists.berkeley.edu"
    assert settings.google_admins_group == "btrack-admins@lists.berkeley.edu"


def test_workers_group_addresses_normalize_but_keep_their_domain():
    class FakeEnv:
        ENV = "development"
        DEV_LOGIN = "1"
        GOOGLE_USERS_GROUP = "  BTrack-Users@Lists.Berkeley.EDU "
        GOOGLE_ADMINS_GROUP = "BTrack-Admins@LISTS.berkeley.edu"

    settings = Settings.from_workers_env(FakeEnv())
    assert settings.google_users_group == "btrack-users@lists.berkeley.edu"
    assert settings.google_admins_group == "btrack-admins@lists.berkeley.edu"
