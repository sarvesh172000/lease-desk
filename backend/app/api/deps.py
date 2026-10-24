"""What every read route depends on, each one overridable in tests.

    app.dependency_overrides[get_engine] = lambda: engines["lease_api"]

The API connects as `lease_api` and nothing else; the role is named here, at
the one call site, as db/engine.py asks.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends
from sqlalchemy.engine import Engine

from ..db.engine import engine
from ..docs.storage import LocalStorage
from ..settings import get_settings

# The business date when nothing better is known. The generated world bills
# January 2026, so that is the month the portfolio is "as of" by default.
# TODO(A7): read the stored business date from jobs/clock.py once it lands.
DEFAULT_BUSINESS_DATE = date(2026, 1, 1)


def get_engine() -> Engine:
    return engine("lease_api")


def get_data_dir() -> Path:
    """Where `make seed` reads the generated company: the lease register
    (`leases/*.json`) and the content-addressed store (`documents/`)."""
    return Path(get_settings().data_dir)


def get_business_date() -> date:
    return DEFAULT_BUSINESS_DATE


def get_storage(data_dir: Path = Depends(get_data_dir)) -> Optional[LocalStorage]:
    """The document store, or None when nothing has been generated yet (so a
    read never creates directories as a side effect)."""
    root = data_dir / "documents"
    return LocalStorage(root) if root.is_dir() else None


def require_reader() -> None:
    """Who may read. Open for now.

    TODO(A8 auth): replace with `Depends(current_actor)` from app/auth once it
    lands, so every read names an actor (and region scope can filter).
    """
    return None
