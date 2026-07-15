# Primary Skill Category Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DM8-backed single primary category for every logical Skill, require category selection during Web publication, and support category display and filtering.

**Architecture:** Store category definitions in `skill_categories` and the one-per-`namespace/name` relationship in `skill_category_assignments`; do not alter manifest v1 or duplicate classification on version rows. Seed the same taxonomy in DM8 migration SQL and SQLite test initialization, default non-Web/history ingestion to `uncategorized`, and let the Web publish endpoint atomically replace that default after a successful release.

**Tech Stack:** Python 3.10+, SQLAlchemy 2, FastAPI/Pydantic, DM8 SQL, Vue 3, Vite, Vitest.

## Global Constraints

- A logical Skill has exactly one primary category; the assignment key is `(namespace, name)`.
- Category is platform metadata and must not be added to `skill.yaml` manifest v1.
- `tags` remain free-form and retain current AND-filter semantics.
- New Web publication requires one enabled, selectable category before Forgejo publication begins.
- Historical, CLI, Webhook, and rebuild ingestion default to the system `uncategorized` category without overwriting an existing assignment.
- Production schema changes are delivered through `infra/dm8-init/`; production code must not auto-create or auto-alter DM8 tables.

---

### Task 1: Category domain model, seed data, and DM8 migration

**Files:**
- Create: `src/skillify/index/categories.py`
- Create: `infra/dm8-init/07-skill-categories.sql`
- Create: `tests/test_index_categories.py`
- Modify: `src/skillify/index/models.py`
- Modify: `src/skillify/index/db.py`
- Modify: `README.md`
- Modify: `infra/README.md`

**Interfaces:**
- Produces: `SkillCategory`, `SkillCategoryAssignment` ORM models.
- Produces: `list_categories(session, *, selectable_only=True) -> list[SkillCategory]`.
- Produces: `get_selectable_category(session, category_id: int) -> SkillCategory | None`.
- Produces: `assign_primary_category(session, *, namespace: str, name: str, category_id: int, now: datetime | None = None) -> SkillCategoryAssignment`.
- Produces: `ensure_default_category(session, *, namespace: str, name: str, now: datetime | None = None) -> SkillCategoryAssignment`.
- Produces: `categories_for_skills(session, keys: list[tuple[str, str]]) -> dict[tuple[str, str], SkillCategory]`.

- [ ] **Step 1: Write failing category model/service tests**

```python
def test_category_seed_and_single_assignment(engine):
    with session_scope(engine) as session:
        choices = list_categories(session)
        assert [item.code for item in choices][:2] == ["writing", "development"]
        assert "uncategorized" not in {item.code for item in choices}
        writing = next(item for item in choices if item.code == "writing")
        development = next(item for item in choices if item.code == "development")
        assign_primary_category(session, namespace="demo", name="helper", category_id=writing.id)
        assign_primary_category(session, namespace="demo", name="helper", category_id=development.id)
    with session_scope(engine) as session:
        assigned = categories_for_skills(session, [("demo", "helper")])
        assert assigned[("demo", "helper")].code == "development"

def test_default_category_does_not_overwrite_manual_assignment(engine):
    with session_scope(engine) as session:
        writing = next(item for item in list_categories(session) if item.code == "writing")
        assign_primary_category(session, namespace="demo", name="helper", category_id=writing.id)
        ensure_default_category(session, namespace="demo", name="helper")
        assert categories_for_skills(session, [("demo", "helper")])[("demo", "helper")].code == "writing"
```

- [ ] **Step 2: Run the tests and confirm missing imports/models fail**

Run: `uv run pytest tests/test_index_categories.py -q`  
Expected: FAIL because `skillify.index.categories` and category models do not exist.

- [ ] **Step 3: Add ORM models and focused category service**

```python
class SkillCategory(Base):
    __tablename__ = "skill_categories"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class SkillCategoryAssignment(Base):
    __tablename__ = "skill_category_assignments"
    namespace: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("skill_categories.id"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Implement idempotent default seeds with codes `writing`, `development`, `data`, `productivity`, `research`, `design-media`, `automation`, `other`, and system-only `uncategorized`. Call the seed function from `init_db()` only for SQLite after `Base.metadata.create_all()`.

- [ ] **Step 4: Add DM8 migration and history backfill**

Create both tables with matching column lengths/types, a foreign key from `skill_category_assignments.category_id`, an index on `category_id`, idempotent `MERGE` statements for all seed categories, and an `INSERT INTO skill_category_assignments (...) SELECT DISTINCT ... FROM skill_index` statement that assigns every existing `skill_index(namespace, name)` to `uncategorized` only when no assignment exists. Update documented SQL execution order to include script 07.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_index_categories.py tests/test_schema_sync.py tests/test_infra_compose.py -q`  
Expected: all tests PASS.

- [ ] **Step 6: Commit the category domain**

```bash
git add src/skillify/index/categories.py src/skillify/index/models.py src/skillify/index/db.py infra/dm8-init/07-skill-categories.sql tests/test_index_categories.py README.md infra/README.md
git commit -m "feat: add primary skill category model"
```

### Task 2: Index ingestion, category filtering, and response enrichment

**Files:**
- Modify: `src/skillify/index/ingest.py`
- Modify: `src/skillify/index/queries.py`
- Modify: `src/skillify/index/my_skills.py`
- Modify: `src/skillify/web/schemas.py`
- Modify: `src/skillify/web/service.py`
- Modify: `src/skillify/web/app.py`
- Modify: `tests/test_index.py`
- Modify: `tests/test_web_app.py`

**Interfaces:**
- Consumes: category service from Task 1.
- Changes: `search(session: Session, query: str | None = None, *, namespace: str | None = None, author: str | None = None, tags: list[str] | None = None, category: str | None = None, sort: str = "updated", page: int = 1, page_size: int = 20, include_yanked: bool = False) -> tuple[list[SkillIndexEntry], int]` filters by enabled category code.
- Changes: `service.list_skills(session: Session, query: str | None = None, *, namespace: str | None = None, author: str | None = None, tags: list[str] | None = None, category: str | None = None, sort: str = "updated", page: int = 1, page_size: int = 20) -> tuple[list[SkillSummary], int]`.
- Produces: `GET /api/categories` and additive `category` fields in `SkillSummary`/`SkillDetail`.

- [ ] **Step 1: Add failing index/API tests**

```python
def test_search_filters_by_primary_category(engine):
    with session_scope(engine) as session:
        upsert_release(session, _event(name="writer"))
        upsert_release(session, _event(name="coder"))
        writing = next(c for c in list_categories(session) if c.code == "writing")
        development = next(c for c in list_categories(session) if c.code == "development")
        assign_primary_category(session, namespace="excel", name="writer", category_id=writing.id)
        assign_primary_category(session, namespace="excel", name="coder", category_id=development.id)
        results, total = search(session, None, category="writing")
        assert total == 1
        assert [item.name for item in results] == ["writer"]
```

Add Web assertions that `/api/categories` excludes `uncategorized`, `/api/skills?category=writing` returns only writing Skills, and each response item exposes `{id, code, name}`.

- [ ] **Step 2: Run focused tests and confirm contract failures**

Run: `uv run pytest tests/test_index.py tests/test_web_app.py -q`  
Expected: FAIL because `category` is not accepted or serialized.

- [ ] **Step 3: Implement SQL category join and batch enrichment**

Join `SkillCategoryAssignment` and `SkillCategory` only when the `category` filter is present, require `SkillCategory.enabled == true`, and filter by exact `SkillCategory.code`. Extend summary aggregation with one batch `categories_for_skills` query, returning `None` only for inconsistent legacy rows.

- [ ] **Step 4: Add schemas and routes**

```python
class SkillCategoryOut(BaseModel):
    id: int
    code: str
    name: str

class SkillSummary(BaseModel):
    namespace: str
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    publishedAt: datetime
    installCount: int
    ratingAverage: float | None
    ratingCount: int
    starCount: int
    category: SkillCategoryOut | None = None

@app.get("/api/categories", response_model=list[SkillCategoryOut])
def skill_categories(_claims: dict = Depends(require_keycloak_user)) -> list[SkillCategoryOut]:
    session = _session()
    try:
        return [SkillCategoryOut(id=item.id, code=item.code, name=item.name) for item in list_categories(session)]
    finally:
        session.close()
```

Pass `category` through both `/api/skills` and `/api/search` to the shared service.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_index.py tests/test_web_app.py tests/test_index_my_skills.py -q`  
Expected: all tests PASS.

- [ ] **Step 6: Commit searchable categories**

```bash
git add src/skillify/index/ingest.py src/skillify/index/queries.py src/skillify/web/schemas.py src/skillify/web/service.py src/skillify/web/app.py tests/test_index.py tests/test_web_app.py
git commit -m "feat: expose and filter skill categories"
```

### Task 3: Enforce and persist category during unified Web publication

**Files:**
- Modify: `src/skillify/web/schemas.py`
- Modify: `src/skillify/web/app.py`
- Modify: `src/skillify/web/formal_publish.py`
- Modify: `tests/test_web_skill_builds.py`
- Modify: `tests/test_publish_index_integration.py`

**Interfaces:**
- Consumes: `get_selectable_category` and `assign_primary_category` from Task 1.
- Changes: `PublishBuildIn` requires `categoryId: int`.
- Changes: `publish_build(cfg: SkillifyConfig, *, owner: str, build_id: str, expected_revision: int, category_id: int) -> tuple[PublishResult, BuildRecord]` and `publish_workspace(skill_root: Path, cfg: SkillifyConfig, *, uploader: str, work_dir: Path, category_id: int) -> PublishResult`.

- [ ] **Step 1: Add failing publication tests**

Add tests that publishing without `categoryId` returns `422`, an unknown/system/disabled category returns `422` before Build status changes, and a successful publish stores the selected category for `(namespace, name)`.

```python
published = client.post(
    f"/api/skill-builds/{build_id}/publish",
    json={"expectedRevision": revision, "confirmed": True, "categoryId": writing_id},
    headers=headers,
)
assert published.status_code == 200
with session_scope(make_engine(index_db_url)) as session:
    assert categories_for_skills(session, [("demo", "hello-skill")])[("demo", "hello-skill")].code == "writing"
```

- [ ] **Step 2: Run publication tests and confirm failure**

Run: `uv run pytest tests/test_web_skill_builds.py tests/test_publish_index_integration.py -q`  
Expected: FAIL because the request and publisher ignore category.

- [ ] **Step 3: Validate before publication and assign after Release success**

Load the category from the configured index database before the Build transition whose target status is `publishing`. Reject absent, disabled, system-only categories with a dedicated `InvalidSkillCategory` mapped to HTTP `422`. After `publish_skill_dir` succeeds, upsert the `(namespace, name)` assignment in `session_scope`; on errors, record the publish job as failed and preserve retry behavior.

- [ ] **Step 4: Keep non-Web ingestion deterministic**

Call `ensure_default_category()` from `upsert_release()` after insert/update so Webhook, CLI, and rebuild paths receive `uncategorized` only when no manual relation exists.

- [ ] **Step 5: Run publication and ingestion tests**

Run: `uv run pytest tests/test_web_skill_builds.py tests/test_publish_index_integration.py tests/test_index.py tests/test_webhook_app.py -q`  
Expected: all tests PASS.

- [ ] **Step 6: Commit publication enforcement**

```bash
git add src/skillify/index/ingest.py src/skillify/web/schemas.py src/skillify/web/app.py src/skillify/web/formal_publish.py tests/test_web_skill_builds.py tests/test_publish_index_integration.py
git commit -m "feat: require category for web publication"
```

### Task 4: Category filter and display in the Skill catalog

**Files:**
- Modify: `web/src/lib/api.js`
- Modify: `web/src/lib/search.js`
- Modify: `web/src/views/SkillListView.vue`
- Modify: `web/src/lang/zh-cn/skills.js`
- Modify: `web/tests/search.spec.js`

**Interfaces:**
- Produces: `listCategories()` API client.
- Changes: `buildSearchParams`, `resolveFilterChange`, and `activeFilterChips` accept `category`.

- [ ] **Step 1: Add failing frontend helper/API tests**

```javascript
expect(buildSearchParams({ category: 'writing', page: 2 })).toMatchObject({ category: 'writing', page: 2 })
expect(activeFilterChips({ category: 'writing', categoryName: '写作' })).toContainEqual({
  type: 'category', label: '写作', value: 'writing',
})
```

Assert `listCategories()` requests `/api/categories` and `listSkills()` forwards the category query parameter.

- [ ] **Step 2: Run tests and confirm failures**

Run: `cd web && npm test -- --run tests/search.spec.js`  
Expected: FAIL because category helpers/client do not exist.

- [ ] **Step 3: Implement catalog category state and UI**

Load categories on mount, render an “全部分类” select, send the selected code with search requests, reset page immediately on category change, include it in clear/remove-chip behavior, and show `skill.category.name` on each result row with an “未分类” fallback.

- [ ] **Step 4: Run catalog tests**

Run: `cd web && npm test -- --run tests/search.spec.js`  
Expected: PASS.

- [ ] **Step 5: Commit catalog UI**

```bash
git add web/src/lib/api.js web/src/lib/search.js web/src/views/SkillListView.vue web/src/lang/zh-cn/skills.js web/tests/search.spec.js
git commit -m "feat: filter skill catalog by category"
```

### Task 5: Required category selector in the publication preview

**Files:**
- Modify: `web/src/lib/api.js`
- Modify: `web/src/components/skillBuilds/BuildWorkspace.vue`
- Modify: `web/src/lang/zh-cn/upload.js`
- Modify: `web/tests/skillBuilds.spec.js`
- Modify: `web/tests/uploadBuildFlow.spec.js`

**Interfaces:**
- Consumes: `listCategories()` from Task 4.
- Changes: `publishSkillBuild(buildId, {expectedRevision, confirmed, categoryId})`.

- [ ] **Step 1: Add failing request and component tests**

```javascript
await publishSkillBuild('b1', { expectedRevision: 3, confirmed: true, categoryId: 7 })
expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
  expectedRevision: 3,
  confirmed: true,
  categoryId: 7,
})
```

Mount `BuildWorkspace` with mocked categories and assert the publish button remains disabled until both confirmation and a category are selected.

- [ ] **Step 2: Run focused tests and confirm failures**

Run: `cd web && npm test -- --run tests/skillBuilds.spec.js tests/uploadBuildFlow.spec.js`  
Expected: FAIL because category selection is absent.

- [ ] **Step 3: Implement required selector and error states**

Fetch categories when the workspace loads, render the selector in the final preview confirmation block, require `selectedCategoryId` in `canPublish`, include it in `publishSkillBuild`, and show retryable loading errors without blocking manifest editing.

- [ ] **Step 4: Run focused frontend tests**

Run: `cd web && npm test -- --run tests/skillBuilds.spec.js tests/uploadBuildFlow.spec.js`  
Expected: PASS.

- [ ] **Step 5: Commit publication UI**

```bash
git add web/src/lib/api.js web/src/components/skillBuilds/BuildWorkspace.vue web/src/lang/zh-cn/upload.js web/tests/skillBuilds.spec.js web/tests/uploadBuildFlow.spec.js
git commit -m "feat: select category when publishing skills"
```

### Task 6: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-07-15-primary-skill-category-design.md` only if implementation behavior differs and the design must be corrected.

**Interfaces:**
- Consumes: all completed tasks.
- Produces: documented API/query/publish contracts and verified release candidate.

- [ ] **Step 1: Update public documentation**

Document `/api/categories`, `category` search query, the additive category response object, required `categoryId` publication payload, the category-vs-tags distinction, and DM8 script 07 execution order.

- [ ] **Step 2: Run backend verification**

Run: `uv run pytest -q`  
Expected: all tests PASS.

Run: `uv run python -m compileall -q src`  
Expected: exit code 0 with no output.

- [ ] **Step 3: Run frontend verification**

Run: `cd web && npm test`  
Expected: all tests PASS.

Run: `cd web && npm run type-check && npm run build`  
Expected: both commands exit 0 and Vite produces `web/dist`.

- [ ] **Step 4: Inspect final diff and schema consistency**

Run: `git diff --check && git status --short`  
Expected: no whitespace errors; status lists only intended category implementation files.

- [ ] **Step 5: Commit documentation/final corrections**

```bash
git add README.md docs/superpowers/specs/2026-07-15-primary-skill-category-design.md
git commit -m "docs: document primary skill categories"
```
