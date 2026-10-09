from alembic import context

from app.config import Settings
from app.db import make_engine
from app.models import Base

config = context.config
target_metadata = Base.metadata


def database_path() -> str:
    # Tests (or callers) can pass an explicit path via `config.attributes["database_path"]`.
    return config.attributes.get("database_path") or Settings.from_env().database_path


def run_migrations_offline() -> None:
    context.configure(
        url=f"sqlite:///{database_path()}",
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(database_path())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
