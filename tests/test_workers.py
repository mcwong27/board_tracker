"""The deferred app-construction path used on Cloudflare Workers.

On Workers the app is built at module scope — before any binding exists — so that the
cost lands in the startup budget and the deploy-time snapshot. Settings are attached on
the first request. These tests cover that path, especially the session signing, which
Starlette normally fixes at construction time.
"""

import pytest
from fastapi.testclient import TestClient

from app.config import ConfigError, Settings
from app.main import create_app
from tests.conftest import make_settings


def attach(app, db, **overrides):
    app.state.settings = make_settings(**overrides).validate()
    app.state.database = db
    return app


def test_deferred_app_builds_without_settings_or_bindings():
    app = create_app(defer=True)
    assert app.state.settings is None
    assert app.state.database is None
    # Authlib can't be imported during module evaluation on Workers, so the OAuth
    # client must not have been built yet.
    assert app.state.oauth is None
    assert app.routes, "routes should be registered at construction time"


def test_deferred_app_serves_once_settings_are_attached(db):
    app = attach(create_app(defer=True), db)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/healthz").text == "ok"
        assert client.get("/login").status_code == 200
        assert client.get("/").status_code == 303  # signed out


def test_deferred_sessions_are_signed_with_the_real_key(db):
    """The session signer is built per request from settings, not at construction."""
    app = attach(create_app(defer=True), db, secret_key="the-real-key")
    with TestClient(app, follow_redirects=False) as client:
        token = _csrf(client)
        resp = client.post("/dev-login", data={"email": "oski@berkeley.edu", "csrf_token": token})
        assert resp.status_code == 303
        # The session cookie round-trips, so signing and verification agree.
        assert client.get("/").status_code == 200
        assert "oski@berkeley.edu" in client.get("/").text


def test_a_session_from_another_key_is_rejected(db):
    """A cookie signed with a different secret must not be accepted."""
    first = attach(create_app(defer=True), db, secret_key="key-one")
    with TestClient(first, follow_redirects=False) as client:
        client.post(
            "/dev-login",
            data={"email": "oski@berkeley.edu", "csrf_token": _csrf(client)},
        )
        stolen = client.cookies.get("btrack_session")
    assert stolen

    second = attach(create_app(defer=True), db, secret_key="key-two")
    with TestClient(second, follow_redirects=False) as client:
        client.cookies.set("btrack_session", stolen)
        assert client.get("/").status_code == 303  # treated as signed out


def test_requests_before_settings_are_attached_fail_loudly(db):
    app = create_app(defer=True)
    app.state.database = db
    with TestClient(app) as client, pytest.raises(RuntimeError, match="settings"):
        client.get("/healthz")


def test_workers_rejects_a_base_url_path_prefix():
    """The app is built before BASE_URL is known, so a prefix can't be honored."""
    settings = make_settings(base_url="https://example.org/btrack")
    assert settings.validate().root_path == "/btrack"  # fine off Workers
    with pytest.raises(ConfigError, match="path prefix"):
        settings.validate(on_workers=True)


def test_workers_settings_without_a_prefix_are_accepted():
    settings = Settings(
        secret_key="x",
        dev_login=False,
        base_url="https://stuff.example.edu",
        google_client_id="id",
        google_client_secret="s",
        google_service_account_json='{"type": "service_account"}',
        google_users_group="u@lists.berkeley.edu",
        google_admins_group="a@lists.berkeley.edu",
    ).validate(on_workers=True)
    assert settings.root_path == ""
    assert settings.https


def _csrf(client: TestClient) -> str:
    import re

    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/dev-login").text)
    assert match
    return match.group(1)
