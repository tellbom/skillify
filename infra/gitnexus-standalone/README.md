# GitNexus standalone MVP

This directory provides a human-facing GitNexus deployment that is isolated
from Skillify CodeGraph, Agent SDK hosting, endpoint tasks, and the codemap
query protocol.

The deployment uses Docker CLI only. Docker Compose is neither required nor
invoked.

## Boundaries

- GitNexus is pinned to `v1.6.9`.
- The official server and web images run as separate containers.
- A minimal Nginx gateway is the only container attached to the host-facing
  bridge network. GitNexus server/web remain on an internal Docker network.
- Imported source is mounted read-only at `/workspace`.
- Containers run with a read-only root filesystem, dropped Linux capabilities,
  `no-new-privileges`, PID limits, and explicit CPU/memory limits.
- The Docker network is internal, so GitNexus cannot fetch repositories or call
  model providers at runtime.
- ZIP and Git URL ingestion happens on the host. Git URLs must use HTTP(S), must
  match `GITNEXUS_ALLOWED_GIT_HOSTS`, and must not contain credentials.
- Private repositories should be exported as an approved ZIP. The MVP does not
  inject Forgejo, SSH, or browser credentials into GitNexus.
- `.gitnexus` indexes contain source-derived content and live beside each
  imported repository under the protected state root. GitNexus registration
  data lives in the persistent named volume. Treat both as source code for
  retention and deletion.

GitNexus OSS remains subject to its upstream noncommercial license. Do not
deploy it for commercial use without the applicable approval or license.

## Server setup

Copy `.env.example` to `.env`. The lifecycle script reads supported values as
plain key/value data and never executes the file as shell code. Process
environment variables still take precedence.

```bash
export GITNEXUS_BIND_HOST=127.0.0.1
export GITNEXUS_STATE_ROOT=/srv/skillify/gitnexus
export GITNEXUS_ALLOWED_GIT_HOSTS=forgejo.internal

scripts/deployment/gitnexus-docker.sh deploy
scripts/deployment/gitnexus-docker.sh status
scripts/deployment/gitnexus-docker.sh mvp-test
```

Open `http://127.0.0.1:4173`. For a remote browser, place an authenticated
reverse proxy in front of the web port and set `GITNEXUS_PUBLIC_URL` and
`GITNEXUS_BACKEND_URL` to that browser-visible origin before `deploy`. The
gateway serves `/api` on the same origin, so port 4747 does not need to be
exposed to users. Do not expose unauthenticated ports to an untrusted network.

The gateway exists because Docker Desktop does not publish host ports for a
container attached only to an `--internal` network. It exposes loopback ports
4173 and 4747 while the source-bearing GitNexus server remains internal.

## Import and index

ZIP:

```bash
scripts/deployment/gitnexus-docker.sh import-zip project-a /approved/project-a.zip
```

Allowed Git URL:

```bash
scripts/deployment/gitnexus-docker.sh import-git project-a \
  https://forgejo.internal/team/project-a.git main
```

Both commands create an isolated directory under
`$GITNEXUS_STATE_ROOT/sources/<repository-id>`. A short-lived, network-disabled
container analyzes the read-only source and writes only its nested `.gitnexus`
directory; the running server then registers that completed index.

Deployment is offline-first: `GITNEXUS_SKIP_PULL=1` is the default. The three
pinned images must be loaded from an approved offline bundle or mirrored in an
internal registry before deployment. GitNexus performs static analysis and
does not install dependencies declared by an uploaded project. The gateway
also removes the upstream Google Fonts URLs, so the browser uses local fallback
fonts instead of attempting a public request.

Run `scripts/deployment/gitnexus-docker.sh prepare-image` once after loading the
official server base image. It builds the local
`skillify/gitnexus:1.6.9-unlimited` overlay with `--pull=false --network=none`.
The overlay removes GitNexus's built-in 250 MiB total, 25 MiB per-file, and
file-count upload caps. Nginx request-body limits are also disabled and request
bodies stream directly to GitNexus instead of using a bounded gateway temp
directory. Docker memory, CPU, and PID quotas default to `0` (not imposed);
operators may set explicit values in `.env` when quotas are required.

Existing repository IDs are never overwritten. Choose a new ID or remove the
old source and its GitNexus index through an approved retention workflow.

## Lifecycle

```bash
scripts/deployment/gitnexus-docker.sh start
scripts/deployment/gitnexus-docker.sh stop
scripts/deployment/gitnexus-docker.sh restart
scripts/deployment/gitnexus-docker.sh logs
scripts/deployment/gitnexus-docker.sh doctor
scripts/deployment/gitnexus-docker.sh mvp-test
```

`stop` and `deploy` do not remove the named index volume. There is deliberately
no broad volume-deletion action in the script.
