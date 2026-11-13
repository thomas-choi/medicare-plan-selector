# API + ingest + purge image (same image, different commands).
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY selector ./selector
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER app
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
