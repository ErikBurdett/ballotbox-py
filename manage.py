#!/usr/bin/env python
"""Repo-root Django management wrapper.

The app is designed to run in Docker Compose. From the repository root, this
wrapper lets developers type ``python manage.py <command>`` and have the command
run in the ``web`` container where Django, GDAL, and PostGIS dependencies exist.

If Django is installed locally, it delegates to ``src/manage.py`` instead.
"""

import os
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC_MANAGE = ROOT / "src" / "manage.py"


def _local_django_available() -> bool:
    try:
        import django  # noqa: F401
    except ImportError:
        return False
    return True


def main() -> None:
    if _local_django_available():
        os.execv(sys.executable, [sys.executable, str(SRC_MANAGE), *sys.argv[1:]])

    quoted_args = " ".join(shlex.quote(arg) for arg in sys.argv[1:])
    inner = "cd /app/src && python manage.py"
    if quoted_args:
        inner = f"{inner} {quoted_args}"

    os.execvp("docker", ["docker", "compose", "exec", "web", "bash", "-lc", inner])


if __name__ == "__main__":
    main()
