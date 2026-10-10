# MeetMind AI API, for Cloud Run.
#
# Deliberately excludes hindsight-all: it pulls torch and transformers and
# loads models for minutes, which does not fit a container that must answer
# a request within seconds of cold start. Memory runs on the MySQL fallback,
# or against a Hindsight server elsewhere via HINDSIGHT_BASE_URL.

FROM python:3.11-slim AS base

# Faster, quieter, and no .pyc files to bloat the layer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not re-download the world.
COPY requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY app ./app
COPY migrations ./migrations

# Run as a non-root user: a container that does not need root should not have it.
RUN useradd --create-home --uid 10001 meetmind \
    && chown -R meetmind:meetmind /app
USER meetmind

# Cloud Run sets PORT and expects the server to listen on it. Default to 8080
# so the image also runs locally with `docker run -p 8080:8080`.
ENV PORT=8080
EXPOSE 8080

# One worker: the app holds per-process state (the Hindsight wiring and its
# retry task), and Cloud Run scales by adding instances rather than workers.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
