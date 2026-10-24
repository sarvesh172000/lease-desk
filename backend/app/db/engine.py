"""One SQLAlchemy engine per database role.

Which role a process connects as is a security decision, so it is made by
name at the call site and never defaulted:

    agent   = engine("lease_agent")     # the worker
    gateway = engine("lease_gateway")   # work/gateway.py, records/golden.py
    api     = engine("lease_api")       # the FastAPI app
    reader  = engine("lease_reader")    # the auditor

`engine("owner")` is for migrations and tests only.
"""

from functools import lru_cache
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ..settings import get_settings


def make_engine(role: str, database: Optional[str] = None) -> Engine:
    """A new engine. Use for a database other than the configured one."""
    return create_engine(get_settings().db_url(role, database or ""), pool_pre_ping=True)


@lru_cache(maxsize=None)
def engine(role: str) -> Engine:
    """The shared engine for one role on the configured database."""
    return make_engine(role)
