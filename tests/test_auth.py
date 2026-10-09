import pytest
from fastapi.testclient import TestClient

from app.auth import IdentityError, validate_identity
from app.main import create_app
from tests.conftest import csrf_from, login, make_settings

GOOD = {"email": "Oski@Berkeley.edu", "email_verified": True, "hd": "berkeley.edu", "name": "Oski"}


def test_valid_identity_is_normalized():
    assert validate_identity(GOOD) == ("oski@berkeley.edu", "Oski")


@pytest.mark.parametrize(
    "changes",
    [
        {"email": "oski@gmail.com", "hd": None},
        {"email": "oski@gmail.com"},  # hd claim alone isn't enough
        {"email": "oski@berkeley.edu.evil.com"},
        {"email": "oski@eecs.berkeley.edu"},
        {"email": "berkeley.edu"},
        {"email_verified": False},
        {"email_verified": None},
        {"hd": None},  # consumer Google account using a berkeley address
        {"hd": "gmail.com"},
    ],
)
def test_invalid_identities_rejected(changes):
    with pytest.raises(IdentityError):
        validate_identity({**GOOD, **changes})


def fake_token(monkeypatch, app, userinfo):
    async def authorize_access_token(request):
        return {"userinfo": userinfo}

    monkeypatch.setattr(app.state.oauth.google, "authorize_access_token", authorize_access_token)


@pytest.fixture
def oauth_app(db_path):
    application = create_app(
        make_settings(db_path, dev_login=False, google_client_id="id", google_client_secret="s")
    )
    yield application
    application.state.engine.dispose()


def test_oauth_callback_rejects_non_berkeley(monkeypatch, oauth_app):
    fake_token(monkeypatch, oauth_app, {**GOOD, "email": "oski@gmail.com", "hd": None})
    with TestClient(oauth_app, follow_redirects=False) as client:
        resp = client.get("/auth/callback")
        assert resp.status_code == 403
        assert "berkeley.edu" in resp.text
        assert client.get("/").status_code == 303  # still signed out


def test_oauth_callback_accepts_berkeley(monkeypatch, oauth_app):
    fake_token(monkeypatch, oauth_app, GOOD)
    with TestClient(oauth_app, follow_redirects=False) as client:
        resp = client.get("/auth/callback")
        assert resp.status_code == 303
        assert client.get("/").status_code == 200


def test_login_google_sends_hd_hint(oauth_app):
    async def fake_metadata():
        return {"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"}

    oauth_app.state.oauth.google.load_server_metadata = fake_metadata
    with TestClient(oauth_app, follow_redirects=False) as client:
        resp = client.get("/login/google")
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "hd=berkeley.edu" in location
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fauth%2Fcallback" in location


def test_dev_login_disabled_without_flag(oauth_app):
    with TestClient(oauth_app) as client:
        assert client.get("/dev-login").status_code == 404


def test_dev_login_rejects_non_berkeley(client):
    token = csrf_from(client, "/dev-login")
    resp = client.post("/dev-login", data={"email": "oski@stanford.edu", "csrf_token": token})
    assert resp.status_code == 403
    assert client.get("/").status_code == 303


def test_unauthenticated_redirects_to_login_then_back(client):
    resp = client.get("/me")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    token = csrf_from(client, "/dev-login")
    resp = client.post("/dev-login", data={"email": "oski@berkeley.edu", "csrf_token": token})
    assert resp.headers["location"] == "/me"


def test_post_without_csrf_rejected(client):
    resp = client.post("/dev-login", data={"email": "oski@berkeley.edu"})
    assert resp.status_code == 403


def test_logout(client):
    login(client, "oski@berkeley.edu")
    assert client.get("/").status_code == 200
    token = csrf_from(client, "/")
    assert client.post("/logout", data={"csrf_token": token}).status_code == 303
    assert client.get("/").status_code == 303


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_base_url_prefix(db_path):
    """Behind a proxy at https://host/boards, links and redirects carry the prefix."""
    settings = make_settings(db_path, base_url="https://example.org/boards")
    with TestClient(create_app(settings), follow_redirects=False) as client:
        resp = client.get("/boards/")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/boards/login"
        assert 'href="/boards/dev-login"' in client.get("/boards/login").text
