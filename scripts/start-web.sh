#!/usr/bin/env bash
set -euo pipefail

python /app/scripts/wait_for_db.py

cd /app/src

python manage.py migrate --noinput
python manage.py collectstatic --noinput || true

exec python manage.py runserver 0.0.0.0:8000
