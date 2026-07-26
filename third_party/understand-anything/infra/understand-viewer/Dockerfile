ARG UA_NODE_IMAGE=node:22.23.1-bookworm-slim

FROM ${UA_NODE_IMAGE} AS build
WORKDIR /build

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY understand-anything-plugin/package.json understand-anything-plugin/package.json
COPY understand-anything-plugin/packages/core/package.json understand-anything-plugin/packages/core/package.json
COPY understand-anything-plugin/packages/dashboard/package.json understand-anything-plugin/packages/dashboard/package.json
COPY understand-anything-plugin/packages/viewer/package.json understand-anything-plugin/packages/viewer/package.json
COPY understand-anything-plugin/packages/tree-sitter-dart-wasm/package.json understand-anything-plugin/packages/tree-sitter-dart-wasm/package.json
COPY understand-anything-plugin/packages/tree-sitter-swift-wasm/package.json understand-anything-plugin/packages/tree-sitter-swift-wasm/package.json
COPY understand-anything-plugin/packages/headless-worker/package.json understand-anything-plugin/packages/headless-worker/package.json

RUN pnpm install --frozen-lockfile --ignore-scripts \
    --filter @understand-anything/core... \
    --filter @understand-anything/dashboard... \
    --filter understand-anything-viewer...

COPY understand-anything-plugin/packages/core understand-anything-plugin/packages/core
COPY understand-anything-plugin/packages/dashboard understand-anything-plugin/packages/dashboard
COPY understand-anything-plugin/packages/viewer understand-anything-plugin/packages/viewer

RUN pnpm --filter understand-anything-viewer build

FROM ${UA_NODE_IMAGE} AS runtime
WORKDIR /opt/understand-viewer

COPY --from=build /build/understand-anything-plugin/packages/viewer/bin ./bin
COPY --from=build /build/understand-anything-plugin/packages/viewer/dist ./dist

ENV NODE_ENV=production
EXPOSE 5173

USER node

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:5173/healthz').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

ENTRYPOINT ["node", "/opt/understand-viewer/bin/viewer.mjs"]
CMD ["/workspace/project", "--host", "0.0.0.0", "--port", "5173", "--no-open"]
