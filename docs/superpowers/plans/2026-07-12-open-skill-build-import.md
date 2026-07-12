# Open Skill Build and Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add preview-first backend APIs for standard zip upload, guided creation, and no-guess external Agent Skill conversion, all converging on one revision-protected publication path.

**Architecture:** Source adapters create owner-bound temporary Native build workspaces under the Skillify cache. A shared preview service exposes the exact manifest and tree with validation/readiness state, while a shared publish service accepts only the previewed revision and reuses existing ownership, Forgejo, packaging, indexing, and publish-job behavior.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, PyYAML, pytest, existing Skillify validator/publisher/Forgejo test fixtures.

## Global Constraints

- Do not add frontend code or a persistent draft box.
- `skill.yaml` manifest v1 is the only canonical metadata model.
- Temporary builds are owner-bound, unlisted, and expire after 86400 seconds by default.
- External import must never infer absent metadata; explicit source facts and explicit user values are the only inputs.
- Git URL import is deferred.
- Every source must publish through the same formal publish service.
- Change `POST /api/skills/upload` from immediate publication to preview creation.
- Follow red-green-refactor and create one local Git commit per task.

---

## File Structure

- `src/skillify/web/build_models.py`: internal dataclasses, API-neutral manifest constants, and build/scan errors.
- `src/skillify/web/build_store.py`: filesystem staging, ownership/expiry/revision checks, safe file mutation, and metadata persistence.
- `src/skillify/web/build_preview.py`: manifest rendering, missing/confirmed field computation, tree serialization, and validation preview.
- `src/skillify/web/build_service.py`: guided/native adapters and canonical build mutation.
- `src/skillify/web/external_import.py`: external zip scanning, fact extraction, candidate selection, and no-guess conversion.
- `src/skillify/web/formal_publish.py`: the only staged-workspace-to-publication orchestration.
- `src/skillify/web/schemas.py`: request/response models for build, scan, mutation, and publish APIs.
- `src/skillify/web/app.py`: authenticated HTTP endpoints and exception-to-HTTP mapping.
- `src/skillify/common/config.py`: `build_ttl_seconds` configuration and environment override.
- `pyproject.toml` / `uv.lock`: Python 3.10-compatible TOML parsing for explicit
  `pyproject.toml` dependency facts.
- `tests/test_web_skill_builds.py`: staging, guided, revision, ownership, expiry, files, and publish API tests.
- `tests/test_web_external_import.py`: scan, multiple candidates, fact extraction, no-guess rules, selection, and conversion tests.
- `tests/test_web_upload.py`: changed standard-upload contract and publication regression tests.
- `README.md`: complete frontend-facing API documentation.

### Task 1: Temporary Native build core and preview

**Files:**
- Create: `src/skillify/web/build_models.py`
- Create: `src/skillify/web/build_store.py`
- Create: `src/skillify/web/build_preview.py`
- Modify: `src/skillify/common/config.py`
- Test: `tests/test_web_skill_builds.py`

**Interfaces:**
- Produces: `BuildStore.create(owner, source_type) -> BuildRecord`, `BuildStore.load(build_id, owner) -> BuildRecord`, `BuildStore.mutate(build_id, owner, expected_revision, mutation) -> BuildRecord`, and `build_preview(record) -> dict[str, Any]`.
- `BuildRecord` exposes `build_id`, `owner`, `source_type`, `revision`, `status`, `expires_at`, `workspace`, `detected_facts`, and `confirmed_fields`.

- [ ] **Step 1: Write failing configuration and store tests**

```python
def test_build_ttl_defaults_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path))
    assert load_config().build_ttl_seconds == 86400
    monkeypatch.setenv("SKILLIFY_BUILD_TTL_SECONDS", "60")
    assert load_config().build_ttl_seconds == 60

def test_build_store_is_owner_bound_revisioned_and_expiring(tmp_path):
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    store = BuildStore(tmp_path, ttl_seconds=60, clock=lambda: now)
    record = store.create("jane", "guided")
    assert record.revision == 1
    with pytest.raises(BuildNotFound):
        store.load(record.build_id, "bob")
    updated = store.mutate(record.build_id, "jane", 1, lambda workspace, meta: None)
    assert updated.revision == 2
    with pytest.raises(BuildRevisionConflict) as exc:
        store.mutate(record.build_id, "jane", 1, lambda workspace, meta: None)
    assert exc.value.current_revision == 2
```

- [ ] **Step 2: Run the focused tests and verify missing symbols fail**

Run: `uv run pytest tests/test_web_skill_builds.py -q`

Expected: collection fails because `BuildStore` and the new configuration field do not exist.

- [ ] **Step 3: Implement the internal records, store, config, and preview**

Use these exact public internal types:

```python
@dataclass
class BuildRecord:
    build_id: str
    owner: str
    source_type: Literal["native_zip", "guided", "external"]
    revision: int
    status: Literal["needs_input", "ready", "publishing", "published"]
    created_at: datetime
    expires_at: datetime
    workspace: Path
    detected_facts: dict[str, Any]
    confirmed_fields: set[str]

class BuildNotFound(Exception): ...

class BuildRevisionConflict(Exception):
    def __init__(self, current_revision: int):
        self.current_revision = current_revision

class BuildStateConflict(Exception): ...
```

Persist metadata as UTF-8 JSON beside `workspace/`, write replacements through a temporary
file plus `Path.replace`, compare owner and UTC expiry before returning records, and remove
expired directories opportunistically. Add `build_ttl_seconds: int = 86400` to
`SkillifyConfig`, load `build_ttl_seconds` from YAML, and parse
`SKILLIFY_BUILD_TTL_SECONDS` with the existing integer override loop.

`build_preview` must load `skill.yaml` when present, generate YAML with
`yaml.safe_dump(..., sort_keys=False, allow_unicode=True)`, read `SKILL.md`, create a sorted
recursive file tree, call `validate_skill_dir(workspace, namespace_aware=False)`, and return
missing required manifest fields plus structured validation issues. Incomplete builds remain
previewable rather than raising validation exceptions.

- [ ] **Step 4: Run focused tests and existing validator tests**

Run: `uv run pytest tests/test_web_skill_builds.py tests/test_validator.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the core node**

```powershell
git add src/skillify/common/config.py src/skillify/web/build_models.py src/skillify/web/build_store.py src/skillify/web/build_preview.py tests/test_web_skill_builds.py
git commit -m "feat: add temporary native skill build core"
```

### Task 2: Guided creation and safe file mutation APIs

**Files:**
- Create: `src/skillify/web/build_service.py`
- Modify: `src/skillify/web/schemas.py`
- Modify: `src/skillify/web/app.py`
- Modify: `tests/test_web_skill_builds.py`

**Interfaces:**
- Consumes: `BuildStore` and `build_preview` from Task 1.
- Produces: `create_guided_build`, `update_build`, `put_build_file`, `delete_build_file`; HTTP endpoints `POST /api/skill-builds/guided`, `GET/PATCH /api/skill-builds/{id}`, and `POST/DELETE /api/skill-builds/{id}/files`.

- [ ] **Step 1: Write failing guided and file API tests**

```python
def test_guided_build_can_be_partial_then_updated(client_with_auth):
    created = client_with_auth.post(
        "/api/skill-builds/guided",
        json={"manifest": {"name": "demo"}, "skillMd": "# Draft"},
    )
    assert created.status_code == 200
    preview = created.json()
    assert preview["sourceType"] == "guided"
    assert "namespace" in preview["missingFields"]
    updated = client_with_auth.patch(
        f"/api/skill-builds/{preview['buildId']}",
        json={"expectedRevision": preview["revision"], "manifest": VALID_MANIFEST_DICT,
              "skillMd": VALID_SKILL_MD},
    )
    assert updated.status_code == 200
    assert updated.json()["publishable"] is True

def test_guided_file_mutation_is_revisioned_and_rejects_reserved_paths(client_with_auth):
    preview = create_valid_guided_build(client_with_auth)
    added = client_with_auth.post(
        f"/api/skill-builds/{preview['buildId']}/files",
        data={"path": "scripts/run.py", "expectedRevision": preview["revision"]},
        files={"file": ("run.py", b"print('ok')", "text/x-python")},
    )
    assert added.status_code == 200
    assert any(item["path"] == "scripts/run.py" for item in added.json()["tree"])
    rejected = client_with_auth.post(
        f"/api/skill-builds/{preview['buildId']}/files",
        data={"path": "skill.yaml", "expectedRevision": added.json()["revision"]},
        files={"file": ("skill.yaml", b"bad", "text/yaml")},
    )
    assert rejected.status_code == 400
```

- [ ] **Step 2: Verify the API tests fail with 404 routes**

Run: `uv run pytest tests/test_web_skill_builds.py -q`

Expected: new requests return `404`.

- [ ] **Step 3: Implement schemas, service functions, and endpoints**

Define Pydantic models with these fields:

```python
class GuidedBuildIn(BaseModel):
    manifest: dict[str, Any] = {}
    skillMd: str = ""

class BuildUpdateIn(BaseModel):
    expectedRevision: int
    manifest: dict[str, Any] | None = None
    skillMd: str | None = None

class BuildTreeItem(BaseModel):
    path: str
    type: str
    size: int | None = None

class ValidationIssueOut(BaseModel):
    path: str
    message: str

class BuildPreviewOut(BaseModel):
    buildId: str
    sourceType: str
    revision: int
    status: str
    expiresAt: datetime
    manifest: dict[str, Any]
    manifestYaml: str
    skillMd: str
    tree: list[BuildTreeItem]
    detectedFacts: dict[str, Any]
    missingFields: list[str]
    unconfirmedFields: list[str]
    issues: list[ValidationIssueOut]
    publishable: bool
```

Write manifest input to `skill.yaml` only through `yaml.safe_dump`; write `skillMd` only to
`SKILL.md`. Normalize uploaded file paths with `PurePosixPath`, reject absolute paths,
backslashes, drive prefixes, empty/dot/parent segments, and case-insensitive reserved paths.
Stream uploads while enforcing `max_upload_bytes`, then enforce total workspace byte and file
limits. Map store exceptions to `404`/`409` and return the canonical preview after every
mutation.

- [ ] **Step 4: Run guided tests and authentication regression tests**

Run: `uv run pytest tests/test_web_skill_builds.py tests/test_web_auth.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the guided API node**

```powershell
git add src/skillify/web/build_service.py src/skillify/web/schemas.py src/skillify/web/app.py tests/test_web_skill_builds.py
git commit -m "feat: add guided skill build APIs"
```

### Task 3: External Agent Skill scan and no-guess conversion

**Files:**
- Create: `src/skillify/web/external_import.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/skillify/web/schemas.py`
- Modify: `src/skillify/web/app.py`
- Test: `tests/test_web_external_import.py`

**Interfaces:**
- Consumes: `safe_extract_zip`, `BuildStore`, `build_preview`, and build mutation from Tasks 1-2.
- Produces: `scan_external_zip` and `select_external_candidates`; HTTP endpoints `POST /api/external-skill-scans` and `POST /api/external-skill-scans/{scan_id}/selections`.

- [ ] **Step 1: Write failing scan, multiple-selection, and no-guess tests**

```python
def test_external_scan_reports_multiple_candidates_and_only_explicit_facts(api, zip_bytes):
    response = api.post("/api/external-skill-scans", files={"file": ("skills.zip", zip_bytes, "application/zip")})
    assert response.status_code == 200
    candidates = response.json()["candidates"]
    assert len(candidates) == 2
    first = candidates[0]
    assert first["frontmatter"]["name"] == "alpha"
    assert first["detectedPaths"] == ["requirements.txt", "scripts"]
    assert "namespace" not in first["frontmatter"]
    assert "version" not in first["frontmatter"]

def test_external_selection_requires_explicit_manifest_confirmation(api, scan):
    selected = api.post(
        f"/api/external-skill-scans/{scan['scanId']}/selections",
        json={"candidateIds": [item["candidateId"] for item in scan["candidates"]]},
    )
    assert selected.status_code == 200
    builds = selected.json()["builds"]
    assert len(builds) == 2
    assert "namespace" in builds[0]["missingFields"]
    assert "name" in builds[0]["unconfirmedFields"]
    assert builds[0]["publishable"] is False
```

Also assert that absent author/license/version/runtime/targets/permissions/tags stay absent,
invalid names are not slugified, `package.json` dependencies are reported only as a detected
path, malformed frontmatter produces a candidate issue, no `SKILL.md` returns `422`, and a
different user cannot load or select a scan.

- [ ] **Step 2: Verify external API tests fail with missing routes**

Run: `uv run pytest tests/test_web_external_import.py -q`

Expected: scan requests return `404`.

- [ ] **Step 3: Implement scan storage, fact extraction, and selection**

Define response/request types:

```python
class ExternalCandidateOut(BaseModel):
    candidateId: str
    rootPath: str
    frontmatter: dict[str, Any]
    detectedPaths: list[str]
    pythonRequirements: list[str]
    issues: list[ValidationIssueOut]

class ExternalScanOut(BaseModel):
    scanId: str
    expiresAt: datetime
    candidates: list[ExternalCandidateOut]

class ExternalSelectionIn(BaseModel):
    candidateIds: list[str]

class ExternalSelectionOut(BaseModel):
    builds: list[BuildPreviewOut]
```

Store scans below `cache/skill-scans/<uuid>`, owner-bind their metadata, and apply the same
TTL. Recursively find exact `SKILL.md` filenames. Use the existing `parse_frontmatter`; do
not derive values from paths. Read non-comment, non-empty `requirements.txt` lines verbatim.
For `pyproject.toml`, use `tomllib` on Python 3.11+ and the conditional dependency
`tomli>=2.0; python_version < '3.11'` on Python 3.10. Read only
`project.dependencies`; do not execute build backends or tool plugins. Update `uv.lock` with
`uv lock`. Copy each selected candidate root into a new external build. Seed only explicit
frontmatter and dependency facts, mark source-seeded conversion fields unconfirmed, and
require a complete manifest update to add those fields to `confirmed_fields`.

- [ ] **Step 4: Run external, zip safety, and validator tests**

Run: `uv run pytest tests/test_web_external_import.py tests/test_web_upload.py::test_upload_rejects_path_traversal_zip tests/test_validator.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the external import node**

```powershell
git add pyproject.toml uv.lock src/skillify/web/external_import.py src/skillify/web/schemas.py src/skillify/web/app.py tests/test_web_external_import.py
git commit -m "feat: add no-guess external skill conversion"
```

### Task 4: Standard zip preview and unified formal publication

**Files:**
- Create: `src/skillify/web/formal_publish.py`
- Modify: `src/skillify/web/build_service.py`
- Modify: `src/skillify/web/upload_service.py`
- Modify: `src/skillify/web/schemas.py`
- Modify: `src/skillify/web/app.py`
- Modify: `tests/test_web_skill_builds.py`
- Modify: `tests/test_web_upload.py`

**Interfaces:**
- Consumes: Native builds and current publisher dependencies.
- Produces: `create_native_zip_build(...) -> BuildRecord`, `publish_build(...) -> PublishResult`; `POST /api/skills/upload` preview semantics and `POST /api/skill-builds/{id}/publish` final confirmation.

- [ ] **Step 1: Change upload tests first and add shared-publish tests**

Replace the immediate-publication expectation with:

```python
def test_standard_upload_previews_before_it_publishes(configured_api, fake_forgejo):
    preview_response = configured_api.post(
        "/api/skills/upload",
        files={"file": ("skill.zip", valid_native_zip(), "application/zip")},
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["sourceType"] == "native_zip"
    assert preview["publishable"] is True
    assert ForgejoClient(fake_forgejo.url, "tok").get_release_by_tag("excel", "pivot-analysis", "v0.1.0") is None

    published = configured_api.post(
        f"/api/skill-builds/{preview['buildId']}/publish",
        json={"expectedRevision": preview["revision"], "confirmed": True},
    )
    assert published.status_code == 200
    assert published.json()["version"] == "0.1.0"
```

Add tests that guided, external, and native builds all call `formal_publish.publish_workspace`,
that stale/unconfirmed/not-ready/cross-user/duplicate confirmations fail, and that the
published `skill.yaml` and tree match the last preview.

- [ ] **Step 2: Run changed tests and observe old immediate-publish behavior fail**

Run: `uv run pytest tests/test_web_upload.py tests/test_web_skill_builds.py tests/test_web_external_import.py -q`

Expected: standard upload returns the old publication response and the new publish route is
missing.

- [ ] **Step 3: Refactor the formal publish service and endpoint**

Move the post-extraction portion of `handle_upload` into:

```python
def publish_workspace(
    skill_root: Path,
    cfg: SkillifyConfig,
    *,
    uploader: str,
    work_dir: Path,
) -> PublishResult:
    """Validate and publish one canonical Native workspace through the sole formal path."""
```

It must preserve current declared-name validation, namespace claim, Git push, release notes,
publication, and best-effort job recording. `create_native_zip_build` safely extracts and
copies a resolvable Native root into staging without calling the publisher.

Define:

```python
class PublishBuildIn(BaseModel):
    expectedRevision: int
    confirmed: bool

class PublishBuildOut(UploadResponse):
    buildId: str
    revision: int
```

The publish endpoint verifies owner, expiry, `confirmed is True`, revision, readiness, and
fresh validation; marks `publishing`; calls `publish_workspace`; marks `published` on
success; and restores `ready` on a retryable publication failure. Standard upload now returns
`BuildPreviewOut` and every entry uses this endpoint.

- [ ] **Step 4: Run all backend web build/upload tests**

Run: `uv run pytest tests/test_web_upload.py tests/test_web_skill_builds.py tests/test_web_external_import.py tests/test_web_auth.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit the unified publication node**

```powershell
git add src/skillify/web/formal_publish.py src/skillify/web/build_service.py src/skillify/web/upload_service.py src/skillify/web/schemas.py src/skillify/web/app.py tests/test_web_upload.py tests/test_web_skill_builds.py tests/test_web_external_import.py
git commit -m "feat: unify preview-confirmed skill publication"
```

### Task 5: API documentation and full verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: all implemented API routes and schemas.
- Produces: frontend-ready API documentation and verified repository state.

- [ ] **Step 1: Verify the generated OpenAPI contract exposes every implemented route**

```powershell
$openapi = uv run python -c "from skillify.web.app import app; import json; print(json.dumps(app.openapi()['paths'], indent=2))"
$openapi | Select-String '/api/skill-builds/guided'
$openapi | Select-String '/api/skill-builds/{build_id}'
$openapi | Select-String '/api/skill-builds/{build_id}/files'
$openapi | Select-String '/api/skill-builds/{build_id}/publish'
$openapi | Select-String '/api/external-skill-scans'
$openapi | Select-String '/api/external-skill-scans/{scan_id}/selections'
```

- [ ] **Step 2: Resolve any OpenAPI/schema mismatch before documentation edits**

Run: `uv run python -c "from skillify.web.app import app; assert all(p in app.openapi()['paths'] for p in ['/api/skill-builds/guided', '/api/skill-builds/{build_id}', '/api/skill-builds/{build_id}/files', '/api/skill-builds/{build_id}/publish', '/api/external-skill-scans', '/api/external-skill-scans/{scan_id}/selections'])"`

Expected: exit code 0. If it fails, correct the route or response-model mismatch and rerun
the relevant Task 2-4 tests before editing README.

- [ ] **Step 3: Document the complete frontend contract in README**

Document:

- the intentional `/api/skills/upload` compatibility change;
- the common `BuildPreviewOut` fields;
- guided create/update/file request examples;
- external scan, multiple selection, explicit completion, and no-guess rules;
- final publish confirmation;
- revision conflict and 24-hour expiry behavior;
- authentication and status/error mapping;
- a frontend sequence for each entry;
- `SKILLIFY_BUILD_TTL_SECONDS` in the environment table;
- Git URL import as deferred, without presenting a callable endpoint.

- [ ] **Step 4: Run fresh full verification**

Run:

```powershell
uv run pytest -q
uv run python -m compileall -q src
git diff --check
```

Expected: 0 test failures, compile exit code 0, and no whitespace errors.

- [ ] **Step 5: Commit documentation and verification node**

```powershell
git add README.md
git commit -m "docs: document open skill build and import APIs"
```
