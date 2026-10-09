#!/bin/sh
set -e

# Fail fast on bad config (e.g. DEV_LOGIN with ENV=production) before touching the DB.
python -c "from app.config import Settings; Settings.from_env().validate()"

alembic upgrade head

# --forwarded-allow-ips '*': trust X-Forwarded-* from the reverse proxy. Safe because
# docker-compose.yml only publishes the port on 127.0.0.1.
exec uvicorn --factory app.main:create_app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips '*'
