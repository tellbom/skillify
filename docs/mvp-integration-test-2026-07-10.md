# Skillify MVP Integration Test Report

Date: 2026-07-10

## Scope

This pass exercised the Vue frontend and FastAPI backend against the real internal
Keycloak and Rbac.Api services. A disposable SQLite database containing the two bundled
example skills was used for Skillify business data because Docker is not installed on the
test workstation.

No credentials or access tokens are stored in this report or in tracked Skillify files.

## Environment

- Keycloak realm: `http://192.168.124.2:18085/realms/master`
- Keycloak client: `skillify-web` (public client, Authorization Code + PKCE)
- Rbac.Api: `http://192.168.124.2:5005`
- RBAC project: `skillify`
- FastAPI: `http://127.0.0.1:8089`
- Vite: `http://127.0.0.1:5173`
- Python: 3.13.0
- Node.js: 24.9.0

## External Bootstrap

- Created the dedicated Keycloak `skillify-web` client.
- Added an access-token audience mapper for `skillify-web`.
- Added a `userid` mapper sourced from the Keycloak username so Rbac.Api can resolve the
  existing employee-number identity instead of falling back to the opaque OIDC `sub`.
- Added one project-super grant and four active menu rules to the DM8 `skillify` project.
- Invalidated the affected Redis user-project and menu caches after the direct DM bootstrap.
- Verified real-token `POST /api/auth/login` and `GET /api/admin/index` responses are HTTP
  200 and return `skills`, `skill-detail`, `upload`, and `leaderboard` routes.

The idempotent DM bootstrap is stored in the RBAC repository as
`sql/rbac-bootstrap-skillify-dm.sql`.

## API Results

- Anonymous `GET /api/skills`: HTTP 401.
- Authenticated catalog list: 2 skills.
- Search for `pivot`: 1 result.
- Skill detail: HTTP 200 with version history and install command.
- Recent leaderboard: 2 rows.
- Comment create/list: passed; author resolved from the real Keycloak token.
- Rating create/update: passed; average 5.0, count 1.
- Orchestration hook: HTTP 200 with an empty object for the bundled example.
- Run event: HTTP 204.
- Invalid upload: HTTP 422 with a structured missing-`skill.yaml` issue.
- Valid example upload: validation passed, then returned HTTP 503 because the local FastAPI
  process intentionally had no Forgejo URL or service token configured.

## Browser Results

Playwright completed a real Keycloak login and verified:

- The OIDC callback fragment is removed from the final Skillify URL.
- Username and the three RBAC-driven navigation entries are visible.
- Both bundled skills render in the catalog.
- Skill detail, leaderboard, and upload routes load through dynamic route registration.
- No browser console errors occurred.
- No HTTP 4xx/5xx responses occurred during the successful browser journey.
- Desktop screenshots showed no overlap.
- At a 390 px viewport, document width equals viewport width after the responsive header fix;
  no horizontal overflow remains.

## Defects Fixed

1. FastAPI rejected freshly issued tokens when the issuer clock was a few seconds ahead.
   JWT validation now permits 30 seconds of skew for `iat` only; expiration remains strict.
2. The router re-used the pre-bootstrap `layout` route name after dynamic routes were added,
   leaving the root page blank. It now re-resolves the original path and query.
3. The mobile header forced navigation and account controls beyond the viewport. It now
   wraps account and navigation rows below 640 px.

## Regression Results

- `uv run pytest -q`: 196 passed, 2 skipped, 2 warnings.
- `npm test`: 14 passed across 2 files.
- `npm run build`: passed.

Known non-blocking warnings:

- Starlette `TestClient` reports the existing `httpx` deprecation warning.
- Tar extraction reports the existing Python 3.14 behavior warning.
- Vite reports several Shiki language chunks above 500 kB.

## Remaining MVP Gaps

- Docker is unavailable on this workstation, so the repository's Forgejo, PostgreSQL,
  devpi, and webhook compose stack was not started.
- The real publish -> Forgejo Release -> index -> install -> per-skill venv workflow remains
  unverified against deployed infrastructure.
- Rbac.Api serves Swagger UI, but `/swagger/v1/swagger.json` returned HTTP 500 during the
  environment probe; the two integration endpoints used by Skillify are healthy.
