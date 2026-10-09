"""Apply Alembic migrations programmatically (used at app startup and in tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def upgrade(database_path: str) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_path"] = database_path
    command.upgrade(cfg, "head")
