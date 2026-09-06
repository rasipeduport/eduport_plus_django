#!/bin/sh
set -e

# Smoke-check the configuration before anything else, so a broken deployment
# reports the real problem immediately instead of timing out against Postgres.
#
# This is not the security gate -- that is validate_production_settings() in
# core/settings_guards.py, which raises at import and stops the process. Here
# --fail-level ERROR catches genuine system-check errors (models, URLs, admin),
# and Django's --deploy warnings (HSTS, SSL redirect, cookie flags) are printed
# for review without blocking: they are deliberate per-environment choices.
echo "[entrypoint] validating deployment configuration ..."
python manage.py check --deploy --fail-level ERROR

echo "[entrypoint] waiting for postgres at ${DB_HOST:-db}:${DB_PORT:-5432} ..."
python - <<'PY'
import os, socket, sys, time

host = os.environ.get("DB_HOST", "db")
port = int(os.environ.get("DB_PORT", "5432"))
deadline = time.time() + 60

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"[entrypoint] postgres is up at {host}:{port}")
            sys.exit(0)
    except OSError:
        time.sleep(1)

print(f"[entrypoint] ERROR: postgres never became reachable at {host}:{port}", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] applying migrations ..."
python manage.py migrate --noinput

echo "[entrypoint] collecting static files ..."
python manage.py collectstatic --noinput --clear

exec "$@"
