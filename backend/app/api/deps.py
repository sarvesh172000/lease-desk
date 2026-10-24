"""What every route depends on, each one overridable in tests.

    app.dependency_overrides[api_engine] = lambda: engines["lease_api"]
    app.dependency_overrides[get_gateway_engine] = lambda: engines["lease_gateway"]

The API serves as `lease_api`. `get_engine` is the same engine auth reads
actors with (`auth.deps.api_engine`), so overriding `api_engine` covers both;
overriding `get_engine` alone still works for read-only tests.

The one other role the API process holds is `lease_gateway`, and only to call
work/gateway.py, which posts and releases on a connection of its own role
(PHASE_1.md group 2). No route runs its own SQL on it.
"""

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends
from sqlalchemy.engine import Engine

from ..auth.deps import api_engine
from ..db.engine import engine
from ..docs.storage import LocalStorage
from ..settings import get_settings

# The business date when nothing better is known. The generated world bills
# January 2026, so that is the month the portfolio is "as of" by default.
# TODO(A7): read the stored business date from jobs/clock.py once it lands.
DEFAULT_BUSINESS_DATE = date(2026, 1, 1)


def get_engine(eng: Engine = Depends(api_engine)) -> Engine:
    return eng


def get_gateway_engine() -> Engine:
    """For work/gateway.py calls only: post_approved_charge, release_batch."""
    return engine("lease_gateway")


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
