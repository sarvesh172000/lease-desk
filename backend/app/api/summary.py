"""GET /api/summary: the dashboard's four tiles, summed on the server.

    {"as_of": "2026-01-01", "active_leases": 5, "open_exceptions": 5,
     "pending_review": 5, "held_total": 25736.36, "held_count": 5,
     "portfolio_liability": 2534083.12}

`held_total` is the money actually being held back: the over-bills only, the
positive variances (billed minus supported) of open holds, i.e. charge checks
the checker proposed to hold that nobody has resolved yet (not approved,
posted, closed or rejected). An under-bill the checker explains is not money
held, so a negative variance never adds to it, and neither does a sum of
absolute values. Summed in Decimal from the same figures /api/exceptions
shows, so the tile equals the list.

`portfolio_liability` is the sum of /api/leases' `liability` on the same
date (leases with no terms on file contribute nothing, as they show null).
`?as_of=` reads both as of another date, as /api/leases does.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Engine

from ..auth.deps import current_actor
from .deps import get_business_date, get_data_dir, get_engine
from .exceptions import open_exceptions
from .leases import portfolio
from .schemas import Summary

router = APIRouter(prefix="/api", tags=["summary"], dependencies=[Depends(current_actor)])

_UNRESOLVED = ("exception", "pending_review", "escalated")


@router.get("/summary", response_model=Summary)
def summary(
    as_of: Optional[date] = Query(None, description="Read the portfolio as of this date"),
    eng: Engine = Depends(get_engine),
    data_dir: Path = Depends(get_data_dir),
    business_date: date = Depends(get_business_date),
) -> Summary:
    when = as_of or business_date
    with eng.connect() as conn:
        holds = [e for e in open_exceptions(conn) if e["status"] in _UNRESOLVED]
    over = [Decimal(str(e["delta"])) for e in holds if e["delta"] is not None and e["delta"] > 0]
    leases = portfolio(eng, data_dir, when)
    liability = sum((Decimal(str(l.liability)) for l in leases if l.liability is not None), Decimal("0"))
    return Summary(
        as_of=when,
        active_leases=sum(1 for l in leases if l.end is None or l.end >= when),
        open_exceptions=len(holds),
        pending_review=sum(1 for e in holds if e["status"] == "pending_review"),
        held_total=float(sum(over, Decimal("0")).quantize(Decimal("0.01"))),
        held_count=len(over),
        portfolio_liability=float(liability.quantize(Decimal("0.01"))),
    )
