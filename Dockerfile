FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git openssl libssl-dev libaio1t64 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY spec ./spec

RUN uv sync --frozen --no-dev

# dmPython loads its bundled DPI/encryption libraries at runtime rather than through
# the extension's direct ELF dependencies.
ENV LD_LIBRARY_PATH=/app/.venv/lib/python3.12/site-packages/dmpython.libs

EXPOSE 8088 8089

ENTRYPOINT ["uv", "run"]
CMD ["skillify-webhook"]
