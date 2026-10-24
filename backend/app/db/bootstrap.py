"""Apply the SQL that defines the database. Called from Alembic migrations.

The schema lives in plain SQL files rather than in Alembic operations because
most of what matters here — triggers, SECURITY DEFINER functions, grants — is
SQL anyway, and one readable file beats the same thing spread across Python.
"""

from pathlib import Path

from sqlalchemy.engine import Connection

from ..settings import DB_ROLES, get_settings

HERE = Path(__file__).resolve().parent
SQL_DIR = HERE / "sql"
ROLES_SQL = HERE / "roles.sql"


def apply_sql_file(conn: Connection, path: Path) -> None:
    execute_raw(conn, path.read_text())


def execute_raw(conn: Connection, sql: str) -> None:
    """Run SQL exactly as written, in the connection's transaction.

    Not text(), which reads ':' in casts and time formats as bind parameters,
    and not exec_driver_sql(), which passes psycopg a parameter list so that
    '%' in RAISE messages becomes a placeholder. A bare cursor with no
    parameters leaves the SQL alone.
    """
    cursor = conn.connection.cursor()
    try:
        cursor.execute(sql)
    finally:
        cursor.close()


def apply_roles(conn: Connection) -> None:
    """Create the four roles if missing, reset their grants to roles.sql, and
    set their login passwords from the environment."""
    apply_sql_file(conn, ROLES_SQL)
    settings = get_settings()
    for role in DB_ROLES:
        password = settings.role_passwords[role].replace("'", "''")
        execute_raw(conn, "ALTER ROLE %s WITH LOGIN PASSWORD '%s'" % (role, password))
