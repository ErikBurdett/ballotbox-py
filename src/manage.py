#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "american_voter_directory.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. This project runs Django in Docker by default. "
            "From the repository root, run: "
            "docker compose exec web bash -lc 'cd /app/src && python manage.py <command>' "
            "or use the root wrapper: python manage.py <command>."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

