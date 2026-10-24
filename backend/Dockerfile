# One image for the api and the worker; Compose picks the command.
# Built from the repo root so the engine and generator packages are included.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend:/app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend backend
COPY datagen datagen
COPY leasedesk leasedesk
COPY eval eval

RUN useradd --create-home --uid 10001 app
USER app
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
