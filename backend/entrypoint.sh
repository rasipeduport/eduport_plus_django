#!/bin/sh
set -e

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
