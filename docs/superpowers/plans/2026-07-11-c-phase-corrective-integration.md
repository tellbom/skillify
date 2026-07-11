# C Phase Corrective Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put phase C on the reviewed DM8/C-3 baseline and correct comment and publish-job ownership isolation.

**Architecture:** Rebase the existing C-phase commits onto `39e03e1`, retaining DM8 as the Skillify business database and Forgejo as the Git/Release owner. Enforce ownership in query identities: comments by route skill plus id, publish jobs by target plus initiator.

**Tech Stack:** Git, Python 3.10+, SQLAlchemy 2, FastAPI, pytest, DM8 incremental SQL, Vue 3, Vitest, vue-tsc, Vite.

## Global Constraints

- Change only P0 baseline integration and the two accepted P1 data-ownership defects.
- Keep Forgejo Git/Release data independent from Skillify DM8 business data.
- Do not add compatibility paths for historical production data.
- Write each regression test and observe the expected failure before production edits.

---

### Task 1: Correct The Git Baseline

**Files:** Existing C-phase and `39e03e1` baseline files affected by rebase conflicts.

**Interfaces:** Produces a `main` whose history contains `39e03e1` followed by all 13 C-phase changes.

- [ ] Create `backup/sonnet-c-phase-pre-integration` at the current `main` tip.
- [ ] Run `git rebase --onto 39e03e1 origin/main main`.
- [ ] Resolve conflicts by retaining DM8 dependencies/configuration, SQLite-only `init_db()`, C-3 Git source publishing, Docker/Nginx deployment, and C-phase features.
- [ ] Verify `git merge-base --is-ancestor 39e03e1 main` exits zero and required files exist.

### Task 2: Bind Comment Deletion To Its Route Skill

**Files:**
- Modify: `tests/test_web_community.py`
- Modify: `src/skillify/index/comments.py`
- Modify: `src/skillify/web/app.py`

**Interfaces:** `soft_delete_comment(session, *, namespace, name, comment_id, actor_username, is_namespace_owner)`.

- [ ] Add a test that creates a comment under `hr/resume`, calls delete through `finance/report`, and expects 404 with the row still undeleted.
- [ ] Run the focused test and confirm it fails because the current lookup uses only `comment_id`.
- [ ] Add namespace/name predicates to the comment lookup and pass route values from FastAPI.
- [ ] Run comment index and Web tests and confirm they pass.

### Task 3: Include Initiator In Publish-Job Identity

**Files:**
- Modify: `tests/test_index_my_skills.py`
- Modify: `src/skillify/index/models.py`
- Modify: `src/skillify/index/publish_jobs.py`
- Modify: `infra/dm8-init/03-c2-my-skills.sql`

**Interfaces:** `record_job_result` remains unchanged; its upsert identity includes `initiator`.

- [ ] Add a test recording the same target for two initiators and assert two independently queryable rows remain.
- [ ] Run the focused test and confirm it fails because the second call overwrites the first row.
- [ ] Add `initiator` to the ORM unique constraint and fallback lookup.
- [ ] Add `initiator` to the matching DM8 unique constraint.
- [ ] Run publish-job index and Web tests and confirm they pass.

### Task 4: Full Verification

**Files:** No production edits expected.

**Interfaces:** Produces evidence for merge readiness.

- [ ] Run `uv run pytest -q` and require all non-environmental tests to pass.
- [ ] Run `npm test`, `npm run type-check`, and `npm run build` in `web`.
- [ ] Generate FastAPI OpenAPI and run `git diff --check`.
- [ ] Inspect final status, history, DM8/Forgejo boundaries, and diff before reporting completion.
