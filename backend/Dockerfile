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
# Runtime user; UID/GID are build args so bind mounts on the host match (default 10001).
ARG APP_UID=10001
ARG APP_GID=10001
RUN uv sync --frozen --no-dev \
    && groupadd --system --gid "${APP_GID}" app \
    && useradd --system --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER app
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
