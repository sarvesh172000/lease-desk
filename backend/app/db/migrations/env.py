"""Alembic environment. Migrations always connect as the database owner.

The URL comes from app.settings unless a caller (the test suite, building a
throwaway database) sets `sqlalchemy.url` on the config first.
"""

from alembic import context
from sqlalchemy import create_engine

from app.settings import get_settings

config = context.config


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or get_settings().db_url("owner")
    engine = create_engine(url)
    with engine.connect() as conn:
        context.configure(connection=conn, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against a database")
run_migrations_online()
