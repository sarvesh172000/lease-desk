"""`make demo-data`'s first step: create the configured database if it is missing.

    LEASEDESK_DB_NAME=leasedesk_demo python -m app.db.ensure_database

Connects as the owner to the `postgres` maintenance database and runs
CREATE DATABASE when `LEASEDESK_DB_NAME` does not exist yet; an existing
database is left exactly as it is (never dropped, never emptied). The roles
and the schema are `make migrate`'s job, not this one's.
"""

import re
import sys

from sqlalchemy import create_engine, text

from ..settings import get_settings

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def ensure_database() -> bool:
    """True if this call created the database."""
    settings = get_settings()
    name = settings.db_name
    if not _NAME.match(name):
        raise ValueError("refusing an unusual database name %r" % name)
    admin = create_engine(settings.db_url("owner", "postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first():
                return False
            conn.execute(text('CREATE DATABASE "%s"' % name))
            return True
    finally:
        admin.dispose()


def main() -> int:
    created = ensure_database()
    print("database %s %s" % (get_settings().db_name, "created" if created else "already exists"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
