# Headless Worker MVP

The headless worker is an independent server-side analysis path for Understand
Anything. It does not use Claude Code and does not integrate with a host
agent's subagent mechanism.

## Pipeline

1. deterministic project scan;
2. deterministic Tree-sitter import and structure extraction;
3. file and project summaries through an OpenAI-compatible intranet LLM;
4. LLM-assisted architecture layers and guided tour;
5. schema validation and atomic `knowledge-graph.json` delivery.

If an individual semantic request fails, the worker keeps the structural graph
and records a warning in `status.json`. A deterministic pipeline failure is
fatal.

## Build and run with Docker CLI

Create the runtime configuration without committing credentials:

```bash
cp infra/understand-headless/worker.env.example \
  infra/understand-headless/worker.env
```

Build the image on a connected build machine:

```bash
scripts/understand-headless-docker.sh build
```

The build uses `--pull=false`. Before building on an isolated machine, load the
configured `UA_NODE_IMAGE` and every required package artifact into the local
Docker/build cache. Production servers should load the completed worker image
instead of rebuilding it.

Export it for an offline server:

```bash
docker save understand-anything/headless-worker:0.1.0 \
  | gzip > understand-anything-headless-worker-0.1.0.tar.gz
```

On the intranet server, load it and analyze a staged source directory:

```bash
docker load -i understand-anything-headless-worker-0.1.0.tar.gz
UA_DOCKER_NETWORK=skillify-llm \
  scripts/understand-headless-docker.sh analyze \
  /srv/skillify/sources/task-123 \
  /srv/skillify/understand/task-123 \
  --language zh
```

The source is mounted read-only. Output and progress are written to the second
directory. Runtime requires access only to the configured intranet LLM
endpoint; it does not download packages or project dependencies.

Pass the API key as a host-side `0600` file instead of storing it in the env
file:

```bash
UA_LLM_API_KEY_FILE_HOST=/run/skillify-secrets/ua-llm-api-key \
UA_DOCKER_NETWORK=skillify-llm \
  scripts/understand-headless-docker.sh analyze SOURCE_DIR OUTPUT_DIR
```

`UA_LLM_JSON_MODE=1` enables the OpenAI-compatible `response_format` request.
`UA_LLM_THINKING=enabled|disabled` is optional and is sent only when configured.

## Output contract

- `knowledge-graph.json`: viewer-compatible graph
- `meta.json`: source digest, model name, structural outcomes, and LLM failure count
- `status.json`: `running | ready | failed`, phase, progress, and bounded operational warnings
- `intermediate/`: deterministic stage input/output retained for MVP diagnosis

The current MVP expects an OpenAI-compatible `/chat/completions` endpoint.
Provider-specific adapters can be added behind the client interface without
changing the worker contract. Claude Code is not present in the image; a
Claude-based fallback is intentionally deferred until the native worker is
evaluated.

## Production viewer

The full upstream Dashboard is built into a separate, versioned viewer image.
The runtime image contains compiled assets only and does not install packages.

```bash
scripts/understand-viewer-docker.sh build
UA_VIEWER_BIND_HOST=0.0.0.0 \
  scripts/understand-viewer-docker.sh start SOURCE_DIR OUTPUT_DIR
UA_VIEWER_PUBLIC_HOST=server.internal \
  scripts/understand-viewer-docker.sh url
```

The container runs as a non-root user with a read-only filesystem, dropped
capabilities, a health check, read-only source/graph mounts, and a persistent
host-side access token. Use `export` plus `docker load` to deploy the completed
image to an offline intranet server. The production server never invokes
`pnpm`, pulls an image, or contacts a public package registry.

For the multi-project source-upload and Forgejo workflow, use the production
Portal described in [`portal-production.md`](portal-production.md). The
single-project Viewer remains available for read-only standalone graph
delivery.
