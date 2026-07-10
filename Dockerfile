FROM python:3.12-slim AS base

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY spec ./spec

RUN uv sync --frozen --no-dev

EXPOSE 8088

ENTRYPOINT ["uv", "run", "skillify-webhook"]
