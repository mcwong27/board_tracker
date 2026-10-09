from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.db import make_engine, make_sessionmaker

ROOT = Path(__file__).resolve().parent.parent


def migrate(database_path: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_path"] = database_path
    command.upgrade(cfg, "head")


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test.db")
    migrate(path)
    return path


@pytest.fixture
def db(db_path):
    engine = make_engine(db_path)
    with make_sessionmaker(engine)() as session:
        yield session
    engine.dispose()
