ARG UA_NODE_IMAGE=node:22.23.1-bookworm-slim
FROM ${UA_NODE_IMAGE} AS build

WORKDIR /opt/understand-anything
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY understand-anything-plugin/package.json understand-anything-plugin/package.json
COPY understand-anything-plugin/packages/core/package.json understand-anything-plugin/packages/core/package.json
COPY understand-anything-plugin/packages/headless-worker/package.json understand-anything-plugin/packages/headless-worker/package.json
COPY understand-anything-plugin/packages/tree-sitter-dart-wasm/package.json understand-anything-plugin/packages/tree-sitter-dart-wasm/package.json
COPY understand-anything-plugin/packages/tree-sitter-swift-wasm/package.json understand-anything-plugin/packages/tree-sitter-swift-wasm/package.json
RUN pnpm install --frozen-lockfile --ignore-scripts --filter @understand-anything/headless-worker... --filter @understand-anything/core...

COPY understand-anything-plugin/packages/core understand-anything-plugin/packages/core
COPY understand-anything-plugin/packages/headless-worker understand-anything-plugin/packages/headless-worker
COPY understand-anything-plugin/packages/tree-sitter-dart-wasm understand-anything-plugin/packages/tree-sitter-dart-wasm
COPY understand-anything-plugin/packages/tree-sitter-swift-wasm understand-anything-plugin/packages/tree-sitter-swift-wasm
COPY understand-anything-plugin/skills/understand understand-anything-plugin/skills/understand
RUN pnpm --filter @understand-anything/core build \
 && pnpm --filter @understand-anything/headless-worker build

FROM ${UA_NODE_IMAGE}

ENV NODE_ENV=production
WORKDIR /opt/understand-anything
COPY --from=build /opt/understand-anything /opt/understand-anything

USER node
ENTRYPOINT ["node", "/opt/understand-anything/understand-anything-plugin/packages/headless-worker/dist/cli.js"]
