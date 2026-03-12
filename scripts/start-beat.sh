#!/usr/bin/env bash
set -euo pipefail

python /app/scripts/wait_for_db.py

cd /app/src

exec celery -A american_voter_directory beat -l info
