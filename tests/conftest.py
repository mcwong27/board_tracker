import asyncio
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import SqliteDatabase, apply_schema
from app.main import create_app

SCHEMA = Path(__file__).resolve().parents[1] / "migrations" / "0001_initial.sql"


def run(coro):
    """Drive an async service/db call from a synchronous test."""
    return asyncio.run(coro)


def query(db, sql: str, params: tuple = ()) -> list[dict]:
    return run(db.query(sql, params))


def query_one(db, sql: str, params: tuple = ()) -> dict | None:
    return run(db.query_one(sql, params))


def value(db, sql: str, params: tuple = ()):
    return run(db.value(sql, params))


@pytest.fixture
def db_path(tmp_path) -> str:
    """A SQLite file built from the same SQL that D1 is migrated with."""
    path = str(tmp_path / "test.db")
    apply_schema(path, SCHEMA.read_text())
    return path


@pytest.fixture
def db(db_path):
    database = SqliteDatabase(db_path)
    yield database
    database.close()


ADMIN = "admin@berkeley.edu"


def make_type(db, name: str) -> dict:
    """A fresh database has no asset types, so tests create the ones they need."""
    from app import services

    return run(services.add_asset_type(db, name))


def make_settings(**overrides) -> Settings:
    values = dict(secret_key="test-secret", dev_login=True)
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def app(db):
    return create_app(make_settings(), database=db)


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
