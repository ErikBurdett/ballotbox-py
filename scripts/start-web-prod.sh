#!/usr/bin/env bash
set -euo pipefail

cd /app/src

exec gunicorn american_voter_directory.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers "${WEB_CONCURRENCY:-2}" \
  --threads "${WEB_THREADS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile - \
  --error-logfile -
