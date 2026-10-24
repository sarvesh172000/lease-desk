"""The FastAPI application.

    uvicorn app.main:app --reload            (from backend/, or via `make api`)

It serves as `lease_api`, and holds a `lease_gateway` engine only for the
gateway calls an approval or a batch release makes (api/deps.py). Besides the
routes in api/ and auth/, it answers the two questions an orchestrator asks:
is the process up, and can it reach its data.

CORS lets the Next.js dev server (LEASEDESK_CORS_ORIGINS, default
http://localhost:3000) call it with the session cookie.
"""

from typing import Optional

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .api import ROUTERS
from .auth.routes import router as auth_router
from .db.engine import engine
from .settings import Settings, get_settings


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Lease Desk", version="0.1.0")
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_credentials=True, allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type"])
    app.include_router(auth_router)
    for router in ROUTERS:
        app.include_router(router)

    @app.get("/health")
    def health() -> dict:
        """Liveness: the process is serving. Never touches the database."""
        return {"status": "ok"}

    @app.get("/ready")
    def ready(response: Response) -> dict:
        """Readiness: the API's own role can reach the database, and the
        audit chain verifies. A broken chain is a reason not to serve."""
        try:
            with engine("lease_api").connect() as conn:
                broken = conn.execute(text("SELECT broken_seq FROM audit_verify_chain()")).first()
        except Exception as exc:  # noqa: BLE001 — any failure means not ready
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unavailable", "database": type(exc).__name__}
        if broken is not None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "chain_broken", "broken_seq": broken[0]}
        return {"status": "ready", "database": "ok", "chain": "verified"}

    return app


app = create_app()
