# Production image for the bare halu-core engine (no branding).
# halu-web has its own Dockerfile that builds on top of this one's
# dependency set rather than this image directly, since it needs
# halu-core installed editable from source alongside its own package.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# No compiler or libpq-dev needed: psycopg2-binary ships a prebuilt
# wheel with libpq already bundled, so no apt-get step is required at
# all here (fewer moving parts, no OS package mirror dependency).

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/

RUN pip install --no-cache-dir . psycopg2-binary

RUN useradd --create-home --uid 10001 halu \
    && mkdir -p /app/data \
    && chown -R halu:halu /app
USER halu

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status==200 else 1)"

# Migrate, then serve. A persistent database must already exist and be
# reachable; this never falls back to auto-creating a schema.
CMD ["sh", "-c", "alembic upgrade head && uvicorn halu_core.main:app --host 0.0.0.0 --port 8000"]
