# One image for the api and the worker; Compose picks the command.
# Built from the repo root so the engine and generator packages are included.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/backend:/app

WORKDIR /app
COPY requirements.txt .
# Every requirement ships a manylinux wheel for 3.13 (psycopg[binary], PyMuPDF,
# Pillow, uvloop...), so slim needs no compiler or system libraries. Behind a
# TLS-intercepting proxy this step fails with CERTIFICATE_VERIFY_FAILED; that
# is the network, not the image (see README, "Run it").
RUN pip install --no-cache-dir -r requirements.txt

COPY backend backend
COPY datagen datagen
COPY leasedesk leasedesk
COPY eval eval
# Reference data the code reads: EDGAR exhibits, BLS series, and the committed
# model answers the demo replays (app/llm/client.py REPLAY_DIR). About 350 KB.
COPY data/reference data/reference

RUN useradd --create-home --uid 10001 app
USER app
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
