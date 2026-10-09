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


def test_dev_settings_get_generated_secret():
    s = Settings(dev_login=True).validate()
    assert len(s.secret_key) > 20


def test_from_env(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", " Alice@Berkeley.edu, bob@berkeley.edu ,")
    monkeypatch.setenv("DEV_LOGIN", "1")
    monkeypatch.setenv("BASE_URL", "https://example.org/boards/")
    s = Settings.from_env()
    assert s.admin_emails == {"alice@berkeley.edu", "bob@berkeley.edu"}
    assert s.is_admin("ALICE@berkeley.edu")
    assert s.dev_login
    assert s.root_path == "/boards"
    assert s.https


def test_app_creates_schema_on_startup(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    db_path = str(tmp_path / "fresh" / "tracker.db")
    app = create_app(Settings(dev_login=True, secret_key="x", database_path=db_path))
    with TestClient(app) as client:
        assert client.get("/login").status_code == 200
    app.state.engine.dispose()
