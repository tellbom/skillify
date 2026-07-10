# MVP Integration Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Skillify MVP against the real Keycloak and RBAC services, then verify the FastAPI and Vue application together through the main authenticated user journeys.

**Architecture:** Keycloak authenticates the browser and signs the bearer token consumed by FastAPI. The Vue application sends the same token directly to Rbac.Api to obtain the `skillify` project menu tree, while Skillify business data uses a local SQLite index for this integration pass because Docker is unavailable on the workstation.

**Tech Stack:** Python 3.11, FastAPI, SQLite, Vue 3, Vite, Keycloak, ASP.NET Core Rbac.Api, Dameng DM8

## Global Constraints

- Use the existing Keycloak service at `http://192.168.124.2:18085`.
- Use the existing Rbac.Api service at `http://192.168.124.2:5005`.
- Use RBAC project code `skillify` and the existing administrator user supplied for testing.
- Never write credentials or access tokens to tracked files, logs, screenshots, or test reports.
- Do not alter unrelated `oversia` RBAC rows.
- Keep external bootstrap operations idempotent and verify each write by reading it back.

---

### Task 1: Establish the External Authentication Contract

**Files:**
- Inspect: `web/src/lib/keycloak.js`
- Inspect: `web/src/lib/rbacClient.js`
- Inspect: `src/skillify/web/auth.py`
- Inspect: `E:/router/router/Rbac.Api/appsettings.Development.json`

**Interfaces:**
- Consumes: Keycloak OIDC discovery and Rbac.Api `/api/auth/login`.
- Produces: Confirmed realm URL, public client ID, token audience, redirect origins, RBAC base URL, and project code.

- [ ] **Step 1: Read Keycloak discovery metadata**

Run: `curl.exe -fsS http://192.168.124.2:18085/realms/master/.well-known/openid-configuration`

Expected: JSON with issuer `http://192.168.124.2:18085/realms/master` and reachable JWKS URI.

- [ ] **Step 2: Inspect the existing public client and test user through the Keycloak Admin API**

Run: Query `/admin/realms/master/clients` and `/admin/realms/master/users` using an in-memory admin token.

Expected: An enabled public client with standard flow and a matching enabled user.

- [ ] **Step 3: Mint a short-lived user token and inspect claims in memory**

Run: Request a password-grant token only for diagnostic API calls, decode its payload locally, and discard it after the process exits.

Expected: `iss`, `preferred_username`, `sub`, `azp`, and usable audience claims are present.

### Task 2: Bootstrap the Skillify RBAC Project

**Files:**
- Create: `E:/router/router/sql/rbac-bootstrap-skillify-dm.sql`
- Test: `E:/skillify/web/tests/dynamicRoutes.spec.js`

**Interfaces:**
- Consumes: DM8 RBAC schema and the menu-node contract asserted by `dynamicRoutes.spec.js`.
- Produces: Idempotent `skillify` project grant and four routable menu nodes for user `196045`.

- [ ] **Step 1: Query existing Skillify rows**

Run: `E:\DM\bin\DIsql.exe -L -S <runtime-logon> -E "SELECT ... WHERE \"project\"='skillify';"`

Expected: Existing grant/rule counts are known before any write.

- [ ] **Step 2: Create an idempotent DM8 bootstrap script**

Create rows for routes `skills`, `skill-detail`, `upload`, and `leaderboard`; use component paths matching `import.meta.glob('/src/views/**/*.vue')`; grant project-super access to the supplied administrator.

- [ ] **Step 3: Execute the bootstrap script and read back counts**

Run: `E:\DM\bin\DIsql.exe -L -S <runtime-logon> \`E:\router\router\sql\rbac-bootstrap-skillify-dm.sql`

Expected: One project grant and four active route rules exist for project `skillify`.

- [ ] **Step 4: Verify Rbac.Api responses**

Run: `POST /api/auth/login` and `GET /api/admin/index` with the administrator token and `X-Project: skillify`.

Expected: HTTP 200, response `code` 0, and menu names `skills`, `skill-detail`, `upload`, and `leaderboard` with resolvable Skillify components.

### Task 3: Start the Skillify Backend and Frontend

**Files:**
- Create locally ignored: `web/.env.local`
- Runtime only: process environment for `SKILLIFY_INDEX_DB_URL`, `SKILLIFY_KEYCLOAK_REALM_URL`, and `SKILLIFY_KEYCLOAK_AUDIENCE`

**Interfaces:**
- Consumes: Task 1 OIDC values and Task 2 RBAC project.
- Produces: FastAPI on `127.0.0.1:8089` and Vite on an available local port.

- [ ] **Step 1: Seed a disposable SQLite index**

Run: Use the existing Skillify index models to initialize a database under `.tmp/mvp/` and ingest the repository examples.

Expected: At least the two bundled example skills are queryable.

- [ ] **Step 2: Start FastAPI with runtime-only environment variables**

Run: `uv run uvicorn skillify.web.app:app --host 127.0.0.1 --port 8089`

Expected: `GET http://127.0.0.1:8089/healthz` returns `{"status":"ok"}`.

- [ ] **Step 3: Start Vite with the real Keycloak and RBAC endpoints**

Run: `npm run dev -- --host 127.0.0.1 --port 5173`

Expected: The root document loads and both `/api` and `/rbacServer` development proxies are reachable.

### Task 4: Verify Authenticated Backend APIs

**Files:**
- Test: `tests/test_web_auth.py`
- Test: `tests/test_web_app.py`
- Test: `tests/test_web_upload.py`

**Interfaces:**
- Consumes: A real Keycloak access token and the running FastAPI service.
- Produces: API-level pass/fail evidence for authentication and core market functions.

- [ ] **Step 1: Verify anonymous rejection**

Run: `GET /api/skills` without `Authorization`.

Expected: HTTP 401.

- [ ] **Step 2: Verify authenticated catalog workflows**

Run: Call list, search, detail, leaderboard, comments, rating, and orchestration endpoints with a bearer token.

Expected: Success responses use the documented schemas; unknown skills return 404 rather than 500.

- [ ] **Step 3: Verify upload validation**

Run: Upload an invalid zip, then a valid bundled example package using the same token.

Expected: Invalid content returns structured 422 issues; a valid upload reaches publishing configuration checks without bypassing authentication.

### Task 5: Verify the Browser User Journey

**Files:**
- Test: `web/e2e-check.cjs`
- Test: `web/tests/dynamicRoutes.spec.js`

**Interfaces:**
- Consumes: Running Vite, FastAPI, Keycloak, and Rbac.Api services.
- Produces: Browser evidence for login, dynamic navigation, catalog browsing, and authorization visibility.

- [ ] **Step 1: Open the application and complete Keycloak login**

Run: Launch a Chromium browser at the Vite root and authenticate with the supplied test user.

Expected: The browser returns to Skillify with no token embedded in the URL.

- [ ] **Step 2: Verify RBAC-driven routes**

Run: Inspect navigation and visit `/`, `/leaderboard`, `/upload`, and one `/skills/:namespace/:name` route.

Expected: Routes are dynamically registered from Rbac.Api and no component-resolution errors appear in the console.

- [ ] **Step 3: Verify frontend/backend interaction**

Run: Search the catalog, open a skill detail, load comments, submit a rating, and inspect API responses.

Expected: Requests carry the Keycloak bearer token and complete without CORS, 401, or proxy failures.

### Task 6: Run Regression Suites and Record Results

**Files:**
- Modify only if defects are found: source and focused test files implicated by the failing workflow.
- Create: `docs/mvp-integration-test-2026-07-10.md`

**Interfaces:**
- Consumes: Tasks 1-5 and any narrowly scoped fixes.
- Produces: Reproducible test results, residual blockers, and service URLs.

- [ ] **Step 1: Run backend regression tests**

Run: `uv run pytest`

Expected: All tests pass.

- [ ] **Step 2: Run frontend tests and production build**

Run: `npm test` and `npm run build` from `web/`.

Expected: All tests pass and Vite completes the build.

- [ ] **Step 3: Record exact integration outcomes**

Write service versions, endpoints, pass/fail results, external rows created, and any remaining infrastructure dependency to `docs/mvp-integration-test-2026-07-10.md`; redact all credentials and tokens.

- [ ] **Step 4: Re-run failing checks after each focused fix**

Run: The smallest failing test first, followed by the affected frontend or backend suite.

Expected: The original failure is reproduced before the fix and absent afterward.
