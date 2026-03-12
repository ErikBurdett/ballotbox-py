#!/usr/bin/env bash
set -euo pipefail

cd /app/src

python -m compileall -q /app/src || true

exec "$@"
