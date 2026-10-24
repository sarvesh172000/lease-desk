"""The HTTP API: the routes of docs/DESIGN.md §16 and the work queue.

Every route needs a signed-in person (`auth.deps.current_actor`; 401
otherwise). Reads and work-layer writes run as `lease_api` through
`deps.get_engine`; gateway calls (posting, batch release) run as
`lease_gateway` through `deps.get_gateway_engine`. Tests override both.

The §16 shapes are frozen by the JSON fixtures in DESIGN.md and mirrored in
`schemas.py`; `tests/platform/test_api_contract.py` parses those fixtures out
of DESIGN.md and fails on any drift in keys or value types. The queue's
shapes (items.py) and the batch's (batches.py) have no fixture and are
documented where they are defined.
"""

from .audit import router as audit_router
from .batches import router as batches_router
from .documents import router as documents_router
from .exceptions import router as exceptions_router
from .items import router as items_router
from .leases import router as leases_router
from .summary import router as summary_router

ROUTERS = (leases_router, exceptions_router, audit_router, documents_router, items_router,
           batches_router, summary_router)
