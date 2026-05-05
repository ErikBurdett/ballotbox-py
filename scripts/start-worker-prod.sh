#!/usr/bin/env bash
set -euo pipefail

cd /app/src

exec celery -A american_voter_directory worker \
  --loglevel "${CELERY_LOG_LEVEL:-info}" \
  --concurrency "${CELERY_WORKER_CONCURRENCY:-2}"
