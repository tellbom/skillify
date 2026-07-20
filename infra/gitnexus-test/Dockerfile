FROM node:22.23.1-bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY gitnexus-shared ./gitnexus-shared
COPY gitnexus-web ./gitnexus-web
COPY gitnexus ./gitnexus
COPY LICENSE ./LICENSE

ENV GITNEXUS_BUILD_TIMEOUT_MS=900000
RUN cd gitnexus-shared && npm ci --ignore-scripts --no-audit --no-fund \
    && cd ../gitnexus-web && npm ci --ignore-scripts --no-audit --no-fund \
    && cd ../gitnexus && npm ci --ignore-scripts --no-audit --no-fund \
    && npm rebuild tree-sitter \
    && node node_modules/@ladybugdb/core/install.js \
    && node scripts/build-tree-sitter-grammars.cjs \
    && node scripts/build.js \
    && perl -0pi -e 's@\s*<link[^>]+fonts\.(?:googleapis|gstatic)\.com[^>]*>@@g' web/index.html \
    && ! grep -Eq 'fonts\.(googleapis|gstatic)\.com' web/index.html \
    && node dist/cli/index.js --version

FROM node:22.23.1-bookworm-slim AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libssl3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/gitnexus
COPY --from=build /build/LICENSE ./LICENSE
COPY --from=build /build/gitnexus ./gitnexus

ENV GITNEXUS_SKIP_OPTIONAL_GRAMMARS=1 \
    HOME=/var/lib/gitnexus/home \
    XDG_CONFIG_HOME=/var/lib/gitnexus/home/.config \
    XDG_CACHE_HOME=/var/lib/gitnexus/home/.cache

USER node
ENTRYPOINT ["node", "/opt/gitnexus/gitnexus/dist/cli/index.js"]
CMD ["serve", "--host", "0.0.0.0", "--port", "4747"]
