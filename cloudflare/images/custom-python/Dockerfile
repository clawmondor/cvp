# syntax=docker/dockerfile:1.7
# Built from the REPOSITORY ROOT so it can COPY skills/ directly:
#   docker build -f cloudflare/images/custom-python/Dockerfile .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Baked, not injected — telemetry must describe the image that actually ran.
ARG IMAGE_TAG=dev
ENV IMAGE_TAG=${IMAGE_TAG} \
    AGENT_IMPL=custom-python

RUN pip install --no-cache-dir httpx==0.27.2

WORKDIR /app

COPY cloudflare/images/shared/ /app/
# Used from source rather than duplicated, so the reference client cannot drift.
COPY skills/airecommendations/scripts/agent_client.py /app/agent_client.py

ENTRYPOINT ["python", "/app/runner.py"]
