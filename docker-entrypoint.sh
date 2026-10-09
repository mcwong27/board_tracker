#!/bin/sh
set -e

# Fail fast on bad config (e.g. DEV_LOGIN with ENV=production). The app applies
# migrations itself on startup.
python -c "from app.config import Settings; Settings.from_env().validate()"

# --forwarded-allow-ips '*': trust X-Forwarded-* from the reverse proxy. Safe because
# docker-compose.yml only publishes the port on 127.0.0.1.
exec uvicorn --factory app.main:create_app \
    --host 0.0.0.0 --port 8000 \
    --proxy-headers --forwarded-allow-ips '*'
