import pytest
from fastapi.testclient import TestClient

from app.auth import IdentityError, validate_identity
from app.groups import GroupsError
from app.main import create_app
from tests.conftest import csrf_from, login, make_settings

GOOD = {"email": "Oski@Berkeley.edu", "email_verified": True, "hd": "berkeley.edu", "name": "Oski"}

USERS_GROUP = "boards-users@berkeley.edu"
ADMINS_GROUP = "boards-admins@berkeley.edu"


class FakeGroupsClient:
    """Stands in for app.groups.GroupsClient; tests must never hit the network."""

    def __init__(self, users: set[str] = frozenset(), admins: set[str] = frozenset(), error=None):
        self.users = set(users)
        self.admins = set(admins)
        self.error = error

    def is_member(self, group_email: str, user_email: str) -> bool:
        if self.error is not None:
            raise self.error
        if group_email == USERS_GROUP:
            return user_email in self.users
        if group_email == ADMINS_GROUP:
            return user_email in self.admins
        raise AssertionError(f"unexpected group email: {group_email}")


def fake_groups(monkeypatch, **kwargs) -> FakeGroupsClient:
    client = FakeGroupsClient(**kwargs)
    monkeypatch.setattr("app.routes.auth.get_client", lambda settings: client)
    return client


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
        make_settings(
            db_path,
            dev_login=False,
            google_client_id="id",
            google_client_secret="s",
            google_service_account_json='{"type": "service_account"}',
            google_users_group=USERS_GROUP,
            google_admins_group=ADMINS_GROUP,
        )
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
    fake_groups(monkeypatch, users={"oski@berkeley.edu"})
    with TestClient(oauth_app, follow_redirects=False) as client:
        resp = client.get("/auth/callback")
        assert resp.status_code == 303
        assert client.get("/").status_code == 200


def test_oauth_callback_rejects_non_member_of_users_group(monkeypatch, oauth_app):
    fake_token(monkeypatch, oauth_app, GOOD)
    fake_groups(monkeypatch, users=set())  # not a member of the users group
    with TestClient(oauth_app, follow_redirects=False) as client:
        resp = client.get("/auth/callback")
        assert resp.status_code == 403
        assert "access list" in resp.text
        assert client.get("/").status_code == 303  # still signed out


def test_oauth_callback_grants_non_admin_session(monkeypatch, oauth_app):
    fake_token(monkeypatch, oauth_app, GOOD)
    fake_groups(monkeypatch, users={"oski@berkeley.edu"}, admins=set())
    with TestClient(oauth_app, follow_redirects=False) as client:
        client.get("/auth/callback")
        assert client.get("/admin").status_code == 403


def test_oauth_callback_grants_admin_session(monkeypatch, oauth_app):
    fake_token(monkeypatch, oauth_app, GOOD)
    fake_groups(monkeypatch, users={"oski@berkeley.edu"}, admins={"oski@berkeley.edu"})
    with TestClient(oauth_app, follow_redirects=False) as client:
        client.get("/auth/callback")
        assert client.get("/admin").status_code == 200


def test_oauth_callback_fails_closed_on_groups_api_error(monkeypatch, oauth_app):
    fake_token(monkeypatch, oauth_app, GOOD)
    fake_groups(monkeypatch, error=GroupsError("Cloud Identity API returned 500"))
    with TestClient(oauth_app, follow_redirects=False) as client:
        resp = client.get("/auth/callback")
        assert resp.status_code == 403
        assert "unavailable" in resp.text
        assert client.get("/").status_code == 303  # still signed out


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
    resp = client.get("/assets")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    token = csrf_from(client, "/dev-login")
    resp = client.post("/dev-login", data={"email": "oski@berkeley.edu", "csrf_token": token})
    assert resp.headers["location"] == "/assets"


def test_post_without_csrf_rejected(client):
    resp = client.post("/dev-login", data={"email": "oski@berkeley.edu"})
    assert resp.status_code == 403


def test_dev_login_admin_checkbox_grants_admin(client):
    token = csrf_from(client, "/dev-login")
    client.post(
        "/dev-login",
        data={"email": "oski@berkeley.edu", "admin": "on", "csrf_token": token},
    )
    assert client.get("/admin").status_code == 200


def test_dev_login_without_checkbox_is_not_admin(client):
    token = csrf_from(client, "/dev-login")
    client.post("/dev-login", data={"email": "oski@berkeley.edu", "csrf_token": token})
    assert client.get("/admin").status_code == 403


def test_logout(client):
    login(client, "oski@berkeley.edu")
    assert client.get("/").status_code == 200
    token = csrf_from(client, "/")
    assert client.post("/logout", data={"csrf_token": token}).status_code == 303
    assert client.get("/").status_code == 303


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_base_url_prefix(db_path):
    """Behind a proxy at https://host/assets, links and redirects carry the prefix."""
    settings = make_settings(db_path, base_url="https://example.org/assets")
    with TestClient(create_app(settings), follow_redirects=False) as client:
        resp = client.get("/assets/")
        assert resp.status_code == 303
        assert resp.headers["location"] == "/assets/login"
        assert 'href="/assets/dev-login"' in client.get("/assets/login").text
