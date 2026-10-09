FROM python:3.12-slim

# sqlite3 CLI for online backups (see README).
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini docker-entrypoint.sh ./
COPY migrations ./migrations
COPY app ./app

RUN useradd --system --uid 1000 --home-dir /app app \
    && mkdir -p /data && chown app:app /data
USER app

ENV ENV=production \
    DATABASE_PATH=/data/tracker.db
VOLUME ["/data"]
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
