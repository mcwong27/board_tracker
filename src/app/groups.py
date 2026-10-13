"""Cloud Identity Groups API client: checks *direct* membership in Google Groups.

Used to gate sign-in (the "users" group) and admin rights (the "admins" group).
Membership is checked once, at sign-in time, and the result is cached in the
signed session cookie — see `app/auth.py` and `app/routes/auth.py`. This module
must never be called on every request; that would add network latency to every
page load.

Only *direct* membership is checked, via the non-transitive
`memberships:lookup` endpoint. Nested/child groups are **not** followed: a
user who belongs to a group that is itself a member of the configured group
will not be recognized. The transitive endpoints
(`checkTransitiveMembership`, `searchTransitiveGroups`, `getMembershipGraph`)
require a Workspace Enterprise Standard/Plus/Education or Cloud Identity
Premium license and return 403 without one, so we deliberately avoid them.
See docs/google-groups.md.

Authorization comes from the service account being added as an Owner or
Manager member of each Google Group at groups.google.com. That grants the
service account permission to query the group's membership with no domain-wide
delegation and no Workspace super-admin involvement.
"""

from __future__ import annotations

import functools
import threading

from app.config import ConfigError, Settings

# httpx2, google.auth and google.oauth2 are imported inside the functions that use them:
# importing them while this module is being evaluated fails on Workers with
# "Top-level await in module is unsettled".

API_BASE = "https://cloudidentity.googleapis.com/v1"
SCOPES = ("https://www.googleapis.com/auth/cloud-identity.groups.readonly",)


class GroupsError(Exception):
    """A genuine failure talking to the Cloud Identity API.

    This is distinct from "not a member" (which is a normal False result).
    Callers must fail closed on this — never sign someone in, and never grant
    admin — because we cannot tell whether the person is actually authorized.
    """


class _HttpxAuthRequest:
    """Adapts httpx2 to the `google.auth.transport.Request` interface.

    google-auth's own `requests` transport needs the `requests` package, which
    this project doesn't otherwise depend on; httpx2 is already a dependency.
    """

    def __init__(self, client) -> None:
        self._client = client

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **_kwargs):
        request_kwargs = {"content": body, "headers": headers}
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        try:
            response = self._client.request(method, url, **request_kwargs)
        except Exception as exc:  # noqa: BLE001 - httpx2.HTTPError, imported lazily
            raise GroupsError(f"Network error reaching {url}: {exc}") from exc
        return _HttpxAuthResponse(response)


class _HttpxAuthResponse:
    def __init__(self, response) -> None:
        self._response = response

    @property
    def status(self) -> int:
        return self._response.status_code

    @property
    def headers(self):
        return self._response.headers

    @property
    def data(self) -> bytes:
        return self._response.content


class GroupsClient:
    """Resolves Cloud Identity group resource names and checks direct membership."""

    def __init__(self, credentials, http_client=None) -> None:
        import httpx2

        self._credentials = credentials
        self._http = http_client or httpx2.Client(timeout=10.0)
        self._auth_request = _HttpxAuthRequest(self._http)
        self._resource_names: dict[str, str] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> GroupsClient:
        from google.oauth2 import service_account

        try:
            info = settings.service_account_info()
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=list(SCOPES)
            )
        except (ConfigError, ValueError) as exc:
            raise GroupsError(f"Invalid Cloud Identity service-account credentials: {exc}") from exc
        return cls(credentials)

    def _access_token(self) -> str:
        from google.auth.exceptions import GoogleAuthError

        if not self._credentials.valid:
            try:
                self._credentials.refresh(self._auth_request)
            except GoogleAuthError as exc:
                raise GroupsError(f"Failed to obtain a Cloud Identity access token: {exc}") from exc
        return self._credentials.token

    def _get(self, path: str, params: dict):
        token = self._access_token()
        try:
            return self._http.get(
                f"{API_BASE}/{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except Exception as exc:  # noqa: BLE001 - httpx2.HTTPError, imported lazily
            raise GroupsError(f"Network error calling the Cloud Identity API: {exc}") from exc

    def _group_resource_name(self, group_email: str) -> str:
        """Resolve a group email to its `groups/XXXX` resource name, cached forever."""
        with self._lock:
            cached = self._resource_names.get(group_email)
        if cached:
            return cached
        response = self._get("groups:lookup", {"groupKey.id": group_email})
        if response.status_code != 200:
            raise GroupsError(
                f"Could not resolve group {group_email!r} (is it a Cloud Identity / Google "
                f"Workspace group, and does the service account have access?): "
                f"Cloud Identity API returned {response.status_code}: {response.text}"
            )
        name = response.json().get("name")
        if not name:
            raise GroupsError(f"Cloud Identity lookup for {group_email!r} returned no group name.")
        with self._lock:
            self._resource_names[group_email] = name
        return name

    def is_member(self, group_email: str, user_email: str) -> bool:
        """Return True if `user_email` is a *direct* member of `group_email`.

        A 404 from the membership lookup means "not a member" and returns
        False. Anything else unexpected (401/403/5xx/network error/malformed
        response) raises GroupsError so the caller can fail closed.
        """
        group_name = self._group_resource_name(group_email)
        response = self._get(f"{group_name}/memberships:lookup", {"memberKey.id": user_email})
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise GroupsError(
                f"Membership check for {user_email!r} in {group_email!r} failed: "
                f"Cloud Identity API returned {response.status_code}: {response.text}"
            )
        return True


@functools.lru_cache(maxsize=8)
def get_client(settings: Settings) -> GroupsClient:
    """Return a cached GroupsClient for these settings.

    Caching keeps resolved group resource names and the refreshed OAuth token
    around across sign-ins instead of re-parsing credentials and re-resolving
    groups on every request. `Settings` is a frozen, hashable dataclass, and in
    practice one process has exactly one live `Settings` instance.
    """
    return GroupsClient.from_settings(settings)
