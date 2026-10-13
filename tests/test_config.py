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


def test_app_creates_schema_on_startup(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    db_path = str(tmp_path / "fresh" / "tracker.db")
    app = create_app(Settings(dev_login=True, secret_key="x", database_path=db_path))
    with TestClient(app) as client:
        assert client.get("/login").status_code == 200
    app.state.engine.dispose()
