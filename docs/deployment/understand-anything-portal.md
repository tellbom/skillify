# Understand Anything Portal

Skillify vendors the complete Understand Anything source tree under
`third_party/understand-anything`. It is an isolated code-analysis service and
does not import, replace, or call Skillify's `src/skillify/codemap` package.

The Portal accepts a source folder, ZIP archive, or an internal Forgejo clone
URL. Folder uploads are sent in bounded batches so a browser does not need to
hold one large multipart request open. Dependency, build, cache, and Git
worktree directories are excluded in both the browser and the server.

## Runtime configuration

Create the runtime env and LLM key files outside Git:

```bash
mkdir -p .runtime/understand-anything
chmod 700 .runtime/understand-anything
cp third_party/understand-anything/infra/understand-portal/portal.env.example \
  .runtime/understand-anything/portal.env
printf '%s' "$LLM_API_KEY" > .runtime/understand-anything/llm-api-key
chmod 600 .runtime/understand-anything/llm-api-key
```

The OpenAI-compatible endpoint and model are configured in the runtime file:

```text
.runtime/understand-anything/portal.env
```

For an internal deployment, change `UA_LLM_BASE_URL` and `UA_LLM_MODEL` in that
file. Do not place the API key in an env file.

## Docker CLI operation

No Docker Compose installation is required:

```bash
./scripts/understand-anything-portal.sh build
./scripts/understand-anything-portal.sh start
./scripts/understand-anything-portal.sh status
./scripts/understand-anything-portal.sh url
./scripts/understand-anything-portal.sh logs
./scripts/understand-anything-portal.sh stop
```

Set `UA_PORTAL_PUBLIC_HOST` to the server's internal IP before running `url`
when clients open the Portal from another machine.

The image build uses `--pull=false`. An offline server must preload the pinned
Node base image and the package-manager cache or import a previously exported
Portal image.
