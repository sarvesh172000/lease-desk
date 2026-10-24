"""The API shell: liveness never needs the database, readiness does."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_answers_without_a_database():
    assert TestClient(create_app()).get("/health").json() == {"status": "ok"}


def test_ready_reports_the_chain_verified(engines, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "engine", lambda role: engines[role])
    response = TestClient(main.create_app()).get("/ready")
    assert response.status_code == 200
    assert response.json()["chain"] == "verified"


def test_ready_is_503_when_the_database_is_unreachable(monkeypatch):
    from sqlalchemy import create_engine

    import app.main as main

    dead = create_engine("postgresql+psycopg://x:y@127.0.0.1:1/none",
                         connect_args={"connect_timeout": 1})
    monkeypatch.setattr(main, "engine", lambda role: dead)
    response = TestClient(main.create_app()).get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
