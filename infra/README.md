# Skillify server infrastructure

Skillify uses Docker CLI lifecycle scripts. Docker Compose is not required or
invoked by the supported deployment path.

Forgejo uses its dedicated PostgreSQL volume. Skillify business tables remain
in the separately managed DM8 schema; Skillify does not use Forgejo PostgreSQL
for business data.

## Configure

```sh
cp infra/.env.example infra/.env
```

Set the DM8 URL, Forgejo token, webhook secret, Keycloak settings, RBAC URL,
and endpoint signing secrets in `infra/.env`. Keep real credentials outside
Git.

Before first deployment, create the dedicated DM8 schema and apply the required
files in `infra/dm8-init` with the target installation's DIsql executable.

## Deploy and operate

Run from the repository root on the Linux Docker host:

```sh
sudo scripts/deployment/skillify-docker.sh deploy
sudo scripts/deployment/skillify-docker.sh deploy-code
sudo scripts/deployment/skillify-docker.sh start
sudo scripts/deployment/skillify-docker.sh restart
sudo scripts/deployment/skillify-docker.sh stop
sudo scripts/deployment/skillify-docker.sh status
```

`deploy` builds the backend, frontend, and devpi images; creates missing Docker
network, stateful containers, and named volumes; and recreates only the Web,
webhook, and frontend containers. It never deletes named volumes. Existing
PostgreSQL, Forgejo, and devpi containers are started as-is, so stateful image
or data-format changes remain an explicit maintenance operation.

`deploy-code` is the network-independent application-only path. It compares
the SHA256 of `/app/uv.lock` in the current backend image with the repository
lock and refuses on any mismatch; only then does it overlay the local Skillify
package without resolving dependencies. It also requires a tested
`web/dist/index.html` built on the build client and overlays those static files
onto the existing Nginx image, so the Docker server needs neither Node nor
public-network package access.

The legacy test-server entry point delegates to the same Docker CLI script:

```sh
sudo scripts/deployment/start-test-server-docker.sh
```

When present, the script also starts the existing Keycloak, Redis, and
Elasticsearch containers plus `rbac-api.service` and `rbac-worker.service`.

## Verify

The `deploy`, `start`, and `restart` actions wait for container health and print
a final status table. Useful follow-up commands are:

```sh
curl -f http://127.0.0.1:${SKILLIFY_HTTP_PORT:-8080}/healthz
docker logs --tail 100 skillify-skillify-web-1
docker logs --tail 100 skillify-webhook-1
docker logs --tail 100 skillify-forgejo-1
```

The frontend proxies `/api`, `/healthz`, `/docs`, and `/openapi.json` to the
`skillify-web` container and `/rbac-api/` to the host RBAC service.

For Forgejo tag-push publishing, configure a Forgejo webhook with target
`http://webhook:8088/webhook/forgejo` and the same secret as
`SKILLIFY_WEBHOOK_SECRET`. The `webhook` network alias is created by the script.
