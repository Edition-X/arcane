FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_NO_CACHE=1 \
    ARCANE_HOME=/data/.arcane

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ ./src/

RUN uv sync --no-dev --frozen && \
    mkdir -p /data/.arcane

VOLUME ["/data/.arcane"]

ENTRYPOINT ["arcane", "mcp"]
