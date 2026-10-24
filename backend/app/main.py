"""The FastAPI application.

    uvicorn app.main:app --reload            (from backend/, or via `make api`)

It connects as `lease_api` only. The routes in docs/DESIGN.md §16 arrive with
the work layer and the thin slice (A6–A8); for now it answers the two
questions an orchestrator asks: is the process up, and can it reach its data.
"""

from fastapi import FastAPI, Response, status
from sqlalchemy import text

from .db.engine import engine


def create_app() -> FastAPI:
    app = FastAPI(title="Lease Desk", version="0.1.0")

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
