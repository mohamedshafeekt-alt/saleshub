# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# psycopg2 (not -binary) compiles from source: needs a C compiler, libc + libpq headers
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev libpq-dev \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer — cached separately from app code changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application source
COPY app ./app
COPY alembic.ini ./
COPY scripts ./scripts


# ---------------------------------------------------------------------------
# Runtime — slim image, non-root user, only the venv + source copied in.
# ---------------------------------------------------------------------------
FROM python:3.14-slim

# libpq5: runtime library for psycopg2
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --create-home appuser

WORKDIR /app
COPY --from=builder /app /app

# Local file storage (storage_backend=local) writes under media/ — on the VM
# this is a mounted host folder so uploads survive redeploys.
RUN mkdir -p /app/media && chown -R appuser:app /app/media

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
