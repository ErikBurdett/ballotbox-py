#!/usr/bin/env bash
set -euo pipefail

cd /app/src

exec celery -A american_voter_directory beat \
  --loglevel "${CELERY_LOG_LEVEL:-info}"
