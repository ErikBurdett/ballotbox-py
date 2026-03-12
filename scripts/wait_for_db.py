import os
import sys
import time

import psycopg


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2
    # psycopg doesn't understand the `postgis://` URL scheme (Django does).
    if dsn.startswith("postgis://"):
        dsn = "postgresql://" + dsn[len("postgis://") :]
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]

    deadline = time.time() + int(os.environ.get("DB_WAIT_SECONDS", "60"))
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    cur.fetchone()
            return 0
        except Exception:
            time.sleep(1.0)

    print("Database did not become ready in time", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
