ARG UA_NODE_IMAGE=node:22.23.1-bookworm-slim

FROM ${UA_NODE_IMAGE} AS build
WORKDIR /opt/understand-anything

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY understand-anything-plugin/package.json understand-anything-plugin/package.json
COPY understand-anything-plugin/packages/core/package.json understand-anything-plugin/packages/core/package.json
COPY understand-anything-plugin/packages/dashboard/package.json understand-anything-plugin/packages/dashboard/package.json
COPY understand-anything-plugin/packages/headless-worker/package.json understand-anything-plugin/packages/headless-worker/package.json
COPY understand-anything-plugin/packages/portal/package.json understand-anything-plugin/packages/portal/package.json
COPY understand-anything-plugin/packages/tree-sitter-dart-wasm/package.json understand-anything-plugin/packages/tree-sitter-dart-wasm/package.json
COPY understand-anything-plugin/packages/tree-sitter-swift-wasm/package.json understand-anything-plugin/packages/tree-sitter-swift-wasm/package.json

RUN pnpm install --frozen-lockfile --ignore-scripts \
    --filter @understand-anything/headless-worker... \
    --filter @understand-anything/portal... \
    --filter @understand-anything/dashboard...

COPY understand-anything-plugin/packages/core understand-anything-plugin/packages/core
COPY understand-anything-plugin/packages/dashboard understand-anything-plugin/packages/dashboard
COPY understand-anything-plugin/packages/headless-worker understand-anything-plugin/packages/headless-worker
COPY understand-anything-plugin/packages/portal understand-anything-plugin/packages/portal
COPY understand-anything-plugin/packages/tree-sitter-dart-wasm understand-anything-plugin/packages/tree-sitter-dart-wasm
COPY understand-anything-plugin/packages/tree-sitter-swift-wasm understand-anything-plugin/packages/tree-sitter-swift-wasm
COPY understand-anything-plugin/skills/understand understand-anything-plugin/skills/understand

RUN pnpm --filter @understand-anything/core build \
 && pnpm --filter @understand-anything/headless-worker build \
 && pnpm --filter @understand-anything/dashboard build \
 && mkdir -p understand-anything-plugin/packages/portal/dist \
 && cp -R understand-anything-plugin/packages/dashboard/dist/. \
      understand-anything-plugin/packages/portal/dist/ \
 && chmod +x understand-anything-plugin/packages/portal/bin/git-askpass.mjs

FROM ${UA_NODE_IMAGE} AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client \
 && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production \
    UA_PORTAL_DATA_DIR=/data/projects \
    UA_PORTAL_HOST=0.0.0.0 \
    UA_PORTAL_PORT=5173 \
    UA_WORKER_CLI=/opt/understand-anything/understand-anything-plugin/packages/headless-worker/dist/cli.js

WORKDIR /opt/understand-anything
COPY --from=build /opt/understand-anything /opt/understand-anything

EXPOSE 5173

USER node

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:5173/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

ENTRYPOINT ["node", "/opt/understand-anything/understand-anything-plugin/packages/portal/bin/portal.mjs"]
