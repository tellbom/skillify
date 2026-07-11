FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY spec ./spec

RUN uv sync --frozen --no-dev

EXPOSE 8088 8089

ENTRYPOINT ["uv", "run"]
CMD ["skillify-webhook"]
