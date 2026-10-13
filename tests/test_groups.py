"""Tests for app/groups.py. Never hits the network: a MockTransport stands in
for the Cloud Identity API, and a stub stands in for google-auth credentials.
"""

import httpx2
import pytest

from app.config import Settings
from app.groups import GroupsClient, GroupsError, get_client

USERS_GROUP = "users@berkeley.edu"
GROUP_RESOURCE = "groups/123"


class StubCredentials:
    """A google.auth.credentials.Credentials stand-in that never refreshes."""

    def __init__(self, valid: bool = True, token: str = "fake-token"):
        self.valid = valid
        self.token = token
        self.refresh_calls = 0

    def refresh(self, request):
        self.refresh_calls += 1
        self.valid = True
        self.token = "refreshed-token"


def make_client(handler, credentials: StubCredentials | None = None) -> GroupsClient:
    transport = httpx2.MockTransport(handler)
    http_client = httpx2.Client(transport=transport)
    return GroupsClient(credentials or StubCredentials(), http_client=http_client)


def test_is_member_true_on_200():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("groups:lookup"):
            return httpx2.Response(200, json={"name": GROUP_RESOURCE})
        assert request.url.path == f"/v1/{GROUP_RESOURCE}/memberships:lookup"
        return httpx2.Response(200, json={"name": f"{GROUP_RESOURCE}/memberships/1"})

    client = make_client(handler)
    assert client.is_member(USERS_GROUP, "oski@berkeley.edu") is True


def test_is_member_false_on_404():
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("groups:lookup"):
            return httpx2.Response(200, json={"name": GROUP_RESOURCE})
        return httpx2.Response(404, json={"error": "not found"})

    client = make_client(handler)
    assert client.is_member(USERS_GROUP, "oski@berkeley.edu") is False


def test_group_resource_name_is_cached():
    lookups = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("groups:lookup"):
            lookups.append(1)
            return httpx2.Response(200, json={"name": GROUP_RESOURCE})
        return httpx2.Response(404)

    client = make_client(handler)
    client.is_member(USERS_GROUP, "a@berkeley.edu")
    client.is_member(USERS_GROUP, "b@berkeley.edu")
    assert len(lookups) == 1  # resolved once, reused on the second call


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_membership_lookup_error_raises(status):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("groups:lookup"):
            return httpx2.Response(200, json={"name": GROUP_RESOURCE})
        return httpx2.Response(status, text="denied")

    client = make_client(handler)
    with pytest.raises(GroupsError):
        client.is_member(USERS_GROUP, "oski@berkeley.edu")


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_group_lookup_error_raises(status):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, text="nope")

    client = make_client(handler)
    with pytest.raises(GroupsError):
        client.is_member(USERS_GROUP, "oski@berkeley.edu")


def test_refreshes_token_when_invalid():
    credentials = StubCredentials(valid=False)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer refreshed-token"
        if request.url.path.endswith("groups:lookup"):
            return httpx2.Response(200, json={"name": GROUP_RESOURCE})
        return httpx2.Response(404)

    client = make_client(handler, credentials)
    client.is_member(USERS_GROUP, "oski@berkeley.edu")
    assert credentials.refresh_calls == 1


def test_from_settings_rejects_missing_credentials():
    with pytest.raises(GroupsError):
        GroupsClient.from_settings(Settings())


def test_get_client_is_cached_per_settings(monkeypatch):
    settings = Settings(google_service_account_json='{"type": "service_account"}')

    def fake_from_settings(cls, _settings):
        return cls(StubCredentials())

    monkeypatch.setattr(GroupsClient, "from_settings", classmethod(fake_from_settings))
    get_client.cache_clear()
    try:
        assert get_client(settings) is get_client(settings)
    finally:
        get_client.cache_clear()
