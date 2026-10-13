import re

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import make_engine, make_sessionmaker
from app.main import create_app
from app.migrate import upgrade
from app.models import AssetType


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test.db")
    upgrade(path)
    return path


@pytest.fixture
def db(db_path):
    engine = make_engine(db_path)
    with make_sessionmaker(engine)() as session:
        yield session
    engine.dispose()


ADMIN = "admin@berkeley.edu"


def make_type(db, name: str) -> AssetType:
    """A fresh database has no asset types, so tests create the ones they need."""
    asset_type = AssetType(name=name)
    db.add(asset_type)
    db.commit()
    return asset_type


def make_settings(db_path: str, **overrides) -> Settings:
    values = dict(
        secret_key="test-secret",
        dev_login=True,
        database_path=db_path,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def app(db_path):
    application = create_app(make_settings(db_path))
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, follow_redirects=False) as c:
        yield c


def csrf_from(client: TestClient, url: str) -> str:
    """Load a page and pull the CSRF token out of its forms."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(url).text)
    assert match, f"no CSRF token on {url}"
    return match.group(1)


def login(client: TestClient, email: str, name: str = "") -> None:
    """Dev-login as `email`. Logging in as ADMIN ticks the dev admin checkbox."""
    token = csrf_from(client, "/dev-login")
    data = {"email": email, "name": name, "csrf_token": token}
    if email == ADMIN:
        data["admin"] = "on"
    resp = client.post("/dev-login", data=data)
    assert resp.status_code == 303, resp.text


def post(client: TestClient, url: str, data: dict | None = None, page: str = "/"):
    """POST a form with a valid CSRF token taken from `page`."""
    return client.post(url, data={**(data or {}), "csrf_token": csrf_from(client, page)})
