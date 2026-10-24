"""The read side of the HTTP API: the GET routes of docs/DESIGN.md §16.

Every route reads as `lease_api` through `deps.get_engine`, which tests
override. The shapes are frozen by the JSON fixtures in §16 and mirrored in
`schemas.py`; `tests/platform/test_api_contract.py` parses those fixtures out
of DESIGN.md and fails on any drift in keys or value types.
"""

from .audit import router as audit_router
from .documents import router as documents_router
from .exceptions import router as exceptions_router
from .leases import router as leases_router

ROUTERS = (leases_router, exceptions_router, audit_router, documents_router)
