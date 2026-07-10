# Skillify local infra (T0.3 + T2.1/T2.2 additions)

Forgejo + PostgreSQL + devpi + the webhook packaging service, for local development against
M1's CLI closed loop and M2's automated publish pipeline. Not the production topology —
production is intranet-only Linux (see PLAN.md §0).

## Start

```sh
cd infra
cp .env.example .env
# required for the webhook service — see step 4 below for where these come from:
#   SKILLIFY_FORGEJO_TOKEN=<a Forgejo access token>
#   SKILLIFY_WEBHOOK_SECRET=<any random string; must match the Forgejo webhook config>
docker compose up -d --build
```

## Verify acceptance criteria (T0.3)

1. **Starts with one command**: `docker compose up -d --build` exits 0, `docker compose ps`
   shows `db`, `forgejo`, `devpi`, `webhook` all `running`/`healthy`.

2. **Forgejo can create an org/repo/Release**:
   - Open `http://localhost:3000`, complete first-run install (DB fields are pre-filled from
     env, just confirm), create an admin account.
   - `Site Administration` or the `+` menu → create an organization (e.g. `skillify`).
   - Inside that org, create a repository (e.g. `excel-pivot-analysis`).
   - On that repo, create a Release (any tag) and upload a file as a Release asset — this is
     the exact path `skillctl publish` (T1.3) will drive via the Forgejo API.
   - Generate a personal access token (`Settings → Applications`) — this becomes
     `forgejo_token` in `~/.skillify/config.yaml` / `SKILLIFY_FORGEJO_TOKEN`.

3. **devpi works as a pip index**:
   ```sh
   pip install devpi-client
   devpi use http://localhost:3141
   devpi user -c skillify password=skillify
   devpi login skillify --password=skillify
   devpi index -c dev bases=root/pypi   # inherits from PyPI if the host has internet;
                                          # on a fully offline intranet host, drop the
                                          # `bases=` inheritance and pre-load packages
                                          # via `devpi upload` / mirrored wheels instead.
   devpi use skillify/dev
   pip install --index-url http://localhost:3141/skillify/dev/+simple/ requests
   ```
   A successful `pip install` against that `--index-url` is the acceptance signal; this is
   the same `--index-url` shape `skillctl install` (T1.4/T1.5) will pass through to `uv pip
   install` inside each skill's per-skill venv.

4. **Webhook packaging service (T2.1) receives Forgejo pushes and auto-publishes**:
   - On the org created in step 2, `Settings → Webhooks → Add Webhook → Forgejo`.
     - Target URL: `http://webhook:8088/webhook/forgejo` (container-to-container — Forgejo
       and the webhook service share the `skillify` compose network).
     - Secret: same value as `SKILLIFY_WEBHOOK_SECRET` in `.env`.
     - Trigger: "Push events" (the handler itself filters to tag pushes, see
       `skillify/webhook/handler.py`).
   - Push a tag matching a skill's `skill.yaml` `version` (e.g. `v0.1.0`) to a repo whose root
     contains a valid skill (`skillctl init` scaffolds one). Forgejo delivers the webhook →
     the service fetches that tag's archive, packages it, and publishes the Release — the
     same outcome as running `skillctl publish` locally, without a human running it.
   - Check `docker compose logs webhook` and the repo's Releases page to confirm.

5. **Index DB (T2.2) gets populated automatically by a successful publish**:
   ```sh
   psql "postgresql://forgejo:forgejo@localhost:5432/skillify_index" \
     -c "select namespace, name, version, tags from skill_index;"
   ```
   should show a row for whatever was published in step 4 (or via `skillctl publish` with
   `SKILLIFY_INDEX_DB_URL` pointed at the same DB).

## Known gaps (flagging per the joint-review ask)

- **T0.3's original three services** have **not been run end-to-end** in this session — the
  dev sandbox is Windows without Docker available (`docker: command not found`). The YAML has
  been syntax/schema-sanity-checked (`tests/test_infra_compose.py`), and the image choices +
  env wiring follow each project's documented docker configuration, but nobody has actually
  clicked through steps 2–3 above yet.
- **The `webhook` service + its `Dockerfile`** (repo root) are new in this pass and have the
  same limitation — `uv sync --frozen` inside the Dockerfile has not been build-tested against
  a real Docker daemon; it mirrors the exact `uv sync` invocation exercised interactively in
  this repo throughout development, but the container build itself is unverified.
- Whoever has a Docker host next should run through this whole README top to bottom and report
  back — this is exactly the kind of thing that should get exercised before M2's pipeline is
  pointed at a real intranet Forgejo for real.
