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
# The hosted demo's one-time setup (docs/DEPLOY.md).
COPY deploy/setup-demo.sh deploy/setup-demo.sh
# Reference data: EDGAR exhibits, BLS series, and the committed model answers
# the demo replays (app/llm/client.py REPLAY_DIR). About 350 KB. Not under
# /app/data: Compose mounts the generated data there, which would hide it.
COPY data/reference reference
ENV LEASEDESK_LLM_REPLAY_DIR=/app/reference/llm_cache \
    LEASEDESK_REFERENCE_DIR=/app/reference \
    LEASEDESK_LLM_CACHE_DIR=/tmp/leasedesk-llm-cache
# (The cache default is relative to the working directory, which the app user
# cannot write; Compose points it at a mounted ./.cache instead.)

RUN useradd --create-home --uid 10001 app && mkdir -p /app/data && chown app /app/data
USER app

# The hosted demo (docs/DEPLOY.md) bakes the generated company into /app/data,
# January then July, so the api and worker read the documents the setup job
# seeds with no volume to mount. The generator is deterministic, so they are
# byte for byte the same files. Compose leaves this off and mounts its own.
ARG BAKE_DEMO_DATA=0
RUN if [ "$BAKE_DEMO_DATA" = "1" ]; then \
      python -m datagen.build --out /app/data --month 2026-01 > /dev/null && \
      python -m datagen.build --out /app/data --month 2026-07 > /dev/null; \
    fi
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
