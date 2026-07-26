# Understand Anything Portal

The Portal is a thin production layer in front of the existing Dashboard. It
accepts source folders, ZIP archives, and intranet Forgejo clone URLs, persists
an analysis queue, runs the native headless worker, and opens completed
projects in the unchanged knowledge-graph canvas.

It is independent from the Skillify Agent request path and does not contain
Claude Code.

## Runtime contract

- one versioned image contains the Portal, complete compiled Dashboard,
  headless worker, Git client, and language parsers;
- project sources, job state, worker logs, and graph artifacts live under one
  writable host directory;
- the root filesystem, API key, access token, and all other mounts are
  read-only;
- runtime package installation and image pulls are not performed;
- the worker contacts only `UA_LLM_BASE_URL`;
- Git is contacted only after a user submits a Git source;
- uploaded repositories are scanned as data. Their build/install scripts are
  never executed.
- browser folder uploads and the server independently exclude generated
  dependency/build trees such as `.git`, `node_modules`, `.venv`, `dist`,
  `build`, `bin`, `obj`, `target`, `.ua`, and `.runtime`.

## Build and offline delivery

Build on a connected build machine:

```bash
scripts/understand-portal-docker.sh build
scripts/understand-portal-docker.sh export \
  understand-anything-portal-0.1.0.tar
```

Load the completed image on the intranet server:

```bash
docker load -i understand-anything-portal-0.1.0.tar
```

Copy the example configuration and point it at the intranet OpenAI-compatible
endpoint:

```bash
cp infra/understand-portal/portal.env.example \
  infra/understand-portal/portal.env
```

Store the LLM API key in a host-side `0600` file, then start with Docker CLI:

```bash
UA_LLM_API_KEY_FILE_HOST=/run/skillify-secrets/ua-llm-api-key \
UA_PORTAL_PROJECTS_DIR=/srv/skillify/understand-projects \
UA_PORTAL_BIND_HOST=0.0.0.0 \
UA_PORTAL_PUBLIC_HOST=understand.internal \
  scripts/understand-portal-docker.sh start

UA_PORTAL_PUBLIC_HOST=understand.internal \
  scripts/understand-portal-docker.sh url
```

No Docker Compose command is used.

## Forgejo

HTTP(S) and SCP-style SSH clone addresses are accepted. Configure an optional
host allowlist:

```env
UA_ALLOWED_GIT_HOSTS=forgejo.internal
```

An empty value allows any host reachable from the intranet. For private HTTPS
repositories, mount a service-account token:

```bash
UA_GIT_TOKEN_FILE_HOST=/run/skillify-secrets/forgejo-token \
UA_LLM_API_KEY_FILE_HOST=/run/skillify-secrets/ua-llm-api-key \
  scripts/understand-portal-docker.sh start
```

The token is supplied through `GIT_ASKPASS`; it is not embedded into the clone
URL, job metadata, logs, or image.

## Persistent layout

```text
projects/
  <project-id>/
    job.json
    source/
    graph/
      knowledge-graph.json
      meta.json
      status.json
      intermediate/
    worker.log
```

Jobs in `queued` or `analyzing` state are re-enqueued after a service restart.
Completed graphs remain immediately available.

## Limits

The Portal streams multipart uploads directly to disk. Defaults are deliberately
large for intranet servers:

- upload bytes: 20 GiB;
- expanded ZIP bytes: 40 GiB;
- files per upload: 200,000;
- concurrent analyses: 1.

ZIP entries containing absolute paths, traversal segments, or symbolic links
are rejected. Each limit can be changed in `portal.env`.

## Operations

```bash
scripts/understand-portal-docker.sh status
scripts/understand-portal-docker.sh logs
scripts/understand-portal-docker.sh stop
```

The unauthenticated health endpoint is `GET /healthz`. Project APIs and graph
data require the persisted Portal access token.
