# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint native deps + libpq for psycopg
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libffi8 \
        libpq5 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# uv binary (matches local toolchain)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependency layer — re-runs only when pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App layer
COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# proxy-headers needed because we sit behind Cloudflare + Railway's edge
CMD ["uv", "run", "uvicorn", "claimos.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
