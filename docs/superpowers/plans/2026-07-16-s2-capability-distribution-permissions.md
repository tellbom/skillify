# S2 Capability Distribution and Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install governed Skillify Skill/Workflow/MCP capabilities into OpenCode user or project scope with immutable locks, safe previews, strict local permissions, and exact rollback without damaging user-owned configuration.

**Architecture:** S2 adds three pure foundations first: an immutable capability lock/resolver, a deny-dominant permission engine, and an MCP artifact registry/probe. The OpenCode adapter then consumes those interfaces to plan and atomically apply only owned file or JSON-entry mutations. Existing `skill.yaml`, Forgejo release metadata, checksums, `install/resolver.py`, `install/projector.py`, and OpenCode's native skills/agents/commands/plugins/MCP configuration remain the sources and targets; there is no second catalog, server-side executor, or new resident MCP gateway.

**Tech Stack:** Python 3.11+, dataclasses/enums/protocols, stdlib JSON/hash/subprocess/path handling, existing PyYAML/jsonschema/pytest, Forgejo fakes, temporary directories, pinned OpenCode v1.15.11 contract fixtures.

## Global Constraints

- Upstream authority is `docs/2026-07-15-skillify-endpoint-agent-ecosystem-master-plan.md`; execution rules are `docs/2026-07-16-endpoint-agent-plan.md` and task nodes are `docs/2026-07-16-endpoint-agent-tasks.md`.
- Development is offline: external release, remote MCP, and real OpenCode checks use injected fakes or an exact `pytest.mark.skip(reason="requires test-env: approved internal service and target Linux")` boundary.
- Runtime never downloads from the public internet, invokes a shell for MCP commands, persists a secret, uploads prompt/source, or lets the server access endpoint paths.
- Exact versions, checksums, source release/commit, license, scope, generated ownership, and dependency versions are locked. `latest`, mutable tags, checksum omission, and dependency re-resolution during rollback fail closed.
- Permission combination is deny-dominant. Later declarations cannot override an earlier denial; dangerous actions never become unattended.
- OpenCode project scope has higher precedence than user scope, matching the official v1.15.11 path model: user `~/.config/opencode/{skills,agents,commands,plugins}` and project `.opencode/{skills,agents,commands,plugins}`. Tests inject both roots and never read the developer's real home.
- Skills remain OpenCode-native `SKILL.md`; agents and commands remain Markdown; plugins remain files; MCP remains OpenCode `mcp` configuration. Native file/Shell/Git/test tools are not wrapped as MCP.
- ToolHive/ContextForge decision for G2: do not add either resident gateway in S2. The repository needs metadata generation plus bounded local stdio/remote HTTPS validation, not multi-tenant gateway operations. This avoids a new daemon and unapproved supply chain; reassess when a real shared-gateway requirement and offline/license approval exist.
- Every task follows RED → GREEN → refactor, independent review, `uv run --no-sync python -m compileall -q src`, focused offline pytest, `git diff --check`, and a task-scoped commit. Full backend/frontend regression is required at G2.

## Verified Reuse Map and Execution Order

| Need | Reuse | S2 addition |
| --- | --- | --- |
| Manifest validation | `validator/manifest.py`, `skill-manifest-v1.schema.json` | Strict `entrypoints` shape and relative-reference checks |
| Artifact identity/checksum | `packaging/pack.py`, `install/extract.py`, `install/resolver.py` | Capability lock and fake release catalog |
| Dependency ranges/cycles | `install/dependencies.py`, `install/semver_range.py` | Pure plan resolver that does not install while resolving |
| OpenCode target paths | `install/agent_defaults.py`, `install/projector.py` | Multi-file and JSON-entry owned mutation plan |
| Local endpoint config | `common/config.py`, S1 provider config isolation | Injected user/project capability roots and lock/snapshot store |
| Permissions | manifest `permissions` field | Structured schema, decision lattice, summary and redacted audit |
| MCP packaging/publish | `packaging/pack.py`, `publish/` | Peer MCP metadata model, preview and bounded stdio probe |

Implementation order is **2.2 → 2.3 → 2.4 → 2.1** because Task 2.1 must write the final lock, permission preview, and MCP fragment atomically. The upstream task numbers and requested commit messages remain unchanged.

---

### Task 2.2: Immutable Capability Lock and Pure Dependency Resolution

**Files:**
- Create: `src/skillify/agent/capability_lock.py`
- Create: `tests/test_capability_lock.py`
- Modify: `src/skillify/install/resolver.py`
- Test: `tests/test_resolver.py`
- Test: `tests/test_dependencies.py`

**Interfaces:**
- Consumes: `skillify.install.extract.sha256_file(path: Path) -> str`, existing semver range selection, and Forgejo release identity returned by a fake-injectable catalog.
- Produces: `CapabilityKind`, `InstallScope`, `LockedDependency`, `GeneratedOwnership`, `CapabilityLock`, `CapabilityLockStore`, `ReleaseRecord`, `ReleaseCatalog`, `resolve_capability_graph()`, and `verify_locked_artifact()`.

- [ ] **Step 1: Write failing schema and canonical serialization tests**

Add tests that construct the exact public shapes and reject missing/mutable identity:

```python
def test_capability_lock_is_canonical_and_round_trips(tmp_path: Path) -> None:
    lock = CapabilityLock(
        schema_version=1,
        kind=CapabilityKind.SKILL,
        namespace="excel",
        name="pivot-analysis",
        version="1.2.3",
        forgejo_release="v1.2.3",
        commit="0123456789abcdef0123456789abcdef01234567",
        checksum="a" * 64,
        dependencies=(LockedDependency("skill", "excel/lookup", "2.0.0", "b" * 64),),
        scope=InstallScope.PROJECT,
        generated=(GeneratedOwnership(".opencode/skills/pivot-analysis/SKILL.md", None, "c" * 64),),
        installed_at="2026-07-16T00:00:00+00:00",
    )
    text = lock.to_json()
    assert text == CapabilityLock.from_json(text).to_json()
    assert '"latest"' not in text

@pytest.mark.parametrize("version", ["", "latest", "main", "^1.2.3"])
def test_lock_rejects_non_exact_version(version: str) -> None:
    with pytest.raises(CapabilityLockError, match="exact semantic version"):
        make_lock(version=version)
```

- [ ] **Step 2: Run the lock tests and record RED**

Run: `uv run --no-sync pytest -q tests/test_capability_lock.py`

Expected: collection fails because `skillify.agent.capability_lock` does not exist.

- [ ] **Step 3: Implement immutable lock types and atomic history store**

Implement frozen dataclasses and validation. `GeneratedOwnership.json_pointer` is `None` for a whole file and an RFC-6901 pointer such as `/mcp/repo-search` for a shared JSON entry. The store writes canonical JSON through a mode-0600 temporary file and retains history by lock digest:

```python
class CapabilityKind(str, Enum):
    SKILL = "skill"
    WORKFLOW = "workflow"
    MCP = "mcp"

class InstallScope(str, Enum):
    USER = "user"
    PROJECT = "project"

@dataclass(frozen=True)
class GeneratedOwnership:
    path: str
    json_pointer: str | None
    sha256: str

class CapabilityLockStore:
    def write_current(self, lock: CapabilityLock) -> Path:
        return self._write_atomic(self._current_path(lock), lock.to_json(), mode=0o600)
    def read_current(self, kind: CapabilityKind, namespace: str, name: str) -> CapabilityLock | None:
        path = self._coordinate_path(kind, namespace, name)
        return CapabilityLock.from_json(path.read_text(encoding="utf-8")) if path.is_file() else None
    def read_digest(self, digest: str) -> CapabilityLock:
        return CapabilityLock.from_json(self._history_path(digest).read_text(encoding="utf-8"))
    def remove_current(self, lock: CapabilityLock) -> None:
        self._current_path(lock).unlink(missing_ok=True)
```

Reject absolute/traversing generated paths, invalid JSON pointers, unknown fields, duplicate dependency coordinates, duplicate ownership keys, non-40-hex commits, non-64-hex checksums, and non-UTC/offset-aware timestamps. Sort dependencies and generated ownership by stable keys before serialization.

- [ ] **Step 4: Write failing graph resolution tests for conflict, cycle, missing package, and tampering**

Use an in-memory catalog; no Forgejo/network call is permitted:

```python
def test_resolver_rejects_conflicting_dependency_versions() -> None:
    catalog = FakeReleaseCatalog(records_for_conflicting_diamond())
    with pytest.raises(CapabilityResolveError, match="version conflict"):
        resolve_capability_graph(Coordinate("workflow", "dev/feature", "1.0.0"), catalog)

def test_resolver_rejects_cycle() -> None:
    with pytest.raises(CapabilityResolveError, match="cycle"):
        resolve_capability_graph(Coordinate("skill", "ns/a", "1.0.0"), cycle_catalog())

def test_resolver_rejects_missing_release() -> None:
    with pytest.raises(CapabilityResolveError, match="missing immutable release"):
        resolve_capability_graph(Coordinate("mcp", "tools/echo", "1.0.0"), FakeReleaseCatalog(()))

def test_verify_locked_artifact_rejects_tampering(tmp_path: Path) -> None:
    artifact = tmp_path / "bundle.tar.gz"
    artifact.write_bytes(b"tampered")
    with pytest.raises(CapabilityIntegrityError, match="checksum"):
        verify_locked_artifact(artifact, "a" * 64)
```

- [ ] **Step 5: Implement a pure catalog protocol and deterministic graph resolver**

```python
class ReleaseCatalog(Protocol):
    def get(self, coordinate: Coordinate) -> ReleaseRecord | None:
        raise NotImplementedError

def resolve_capability_graph(root: Coordinate, catalog: ReleaseCatalog) -> tuple[ReleaseRecord, ...]:
    """Depth-first, dependency-before-parent, one exact coordinate per kind/name."""
    return _GraphResolver(catalog).resolve(root)
```

Every input coordinate is exact. A release record contains immutable Forgejo tag, commit, checksum, and exact dependency coordinates. Detect a cycle with an ordered recursion stack; detect same kind/name with different versions; report missing records; sort peer dependencies before traversal. Rollback APIs accept a stored `CapabilityLock` and never call `ReleaseCatalog`.

- [ ] **Step 6: Run GREEN and existing resolver/dependency regression**

Run: `uv run --no-sync pytest -q tests/test_capability_lock.py tests/test_resolver.py tests/test_dependencies.py`

Expected: all pass; no test contacts the network.

- [ ] **Step 7: Commit Task 2.2**

```bash
git add src/skillify/agent/capability_lock.py src/skillify/install/resolver.py tests/test_capability_lock.py tests/test_resolver.py tests/test_dependencies.py
git commit -m "feat(agent): lock installed capabilities"
```

---

### Task 2.3: Deny-Dominant Permission Manifest, Confirmation, and Redacted Audit

**Files:**
- Create: `src/skillify/agent/permissions.py`
- Create: `tests/test_agent_permissions.py`
- Modify: `src/skillify/validator/schemas/skill-manifest-v1.schema.json`
- Modify: `src/skillify/validator/manifest.py`
- Test: `tests/test_validator.py`

**Interfaces:**
- Consumes: structured `permissions` objects from Skill, Workflow, MCP, and task manifests plus a resolved workspace.
- Produces: `PermissionAction`, `OperationKind`, `PermissionManifest`, `OperationRequest`, `PermissionDecision`, `MergedPermissions`, `merge_permissions()`, `summarize_permissions()`, and `write_authorization_audit()`.

- [ ] **Step 1: Write failing manifest-shape and decision-lattice tests**

Replace the legacy string-only permission list with a backward-compatible one-of: legacy strings normalize to named deny/ask policy tags, while the structured object is authoritative for S2.

```python
def test_later_allow_cannot_override_earlier_deny(tmp_path: Path) -> None:
    merged = merge_permissions((policy(command={"rm *": "deny"}), policy(command={"rm *": "allow"})))
    request = OperationRequest(OperationKind.COMMAND, workspace=tmp_path, command=("rm", "-rf", "build"))
    assert merged.decide(request).action is PermissionAction.DENY

def test_allowlists_require_every_policy_to_allow() -> None:
    merged = merge_permissions((policy(network=("git.internal",)), policy(network=("docs.internal",))))
    assert merged.decide(network_request("git.internal")).action is PermissionAction.DENY
```

The schema object has only these keys: `readPaths`, `writePaths`, `commands`, `networkDomains`, `mcpServers`, `databaseResources`, `unattended`, and `confirm`. Path/domain/server/resource lists are explicit allowlists; `commands` maps anchored patterns to `allow|ask|deny`; `confirm` is a list of operation categories.

- [ ] **Step 2: Run permission tests and record RED**

Run: `uv run --no-sync pytest -q tests/test_agent_permissions.py tests/test_validator.py`

Expected: imports or structured manifest validation fail.

- [ ] **Step 3: Implement evaluation without unsafe glob intersection**

Retain every source policy in `MergedPermissions`; evaluate a request against each policy and choose the most restrictive action (`DENY > ASK > ALLOW`). This avoids pretending that arbitrary glob intersections are safe.

```python
class PermissionAction(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

@dataclass(frozen=True)
class MergedPermissions:
    policies: tuple[PermissionManifest, ...]
    def decide(self, request: OperationRequest) -> PermissionDecision:
        decisions = tuple(policy.decide(request) for policy in self.policies)
        return max(decisions, key=lambda item: item.action.restriction_rank)
```

Resolve candidate paths without following a write target outside the workspace. Match domains case-insensitively and reject IP/host suffix tricks. Match commands as argv, never a reconstructed shell string. An empty allowlist denies that dimension unless the explicit token `*` is present.

- [ ] **Step 4: Write failing dangerous-operation and Web-task tests**

```python
@pytest.mark.parametrize("request", [
    command_request(("rm", "-rf", "build")),
    command_request(("sudo", "make", "install")),
    credential_request("MODEL_TOKEN"),
    database_request("orders", write=True),
    write_request("../outside.txt"),
])
def test_dangerous_actions_never_run_unattended(request: OperationRequest) -> None:
    decision = merge_permissions((permissive_policy(),)).decide(request)
    assert decision.action in {PermissionAction.ASK, PermissionAction.DENY}

def test_web_code_write_requires_endpoint_confirmation() -> None:
    request = write_request("src/app.py", origin="web", unattended=True)
    assert merge_permissions((permissive_policy(),)).decide(request).action is PermissionAction.ASK
```

- [ ] **Step 5: Implement summaries and redacted machine audit**

`summarize_permissions()` returns only workspace-relative allowlists, command executable/categories, domain names, MCP names, database resource identifiers, unattended state, and confirmation categories. `write_authorization_audit()` emits JSON Lines with stable enum values and matched policy IDs; it never writes raw prompts, environment values, credential names/values, full external paths, database values, or raw command arguments.

```python
def redact_path(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return f"<external:{hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:12]}>"
```

Validate task IDs and reason codes with bounded character sets. Write audit files mode 0600 through an atomic temporary file or append a single pre-serialized line opened with restrictive creation mode.

- [ ] **Step 6: Run GREEN, validator regression, compile, and secret scan**

Run: `uv run --no-sync pytest -q tests/test_agent_permissions.py tests/test_validator.py`

Run: `uv run --no-sync python -m compileall -q src`

Run: `rg -n "prompt|password|token|secret|environment" tests/test_agent_permissions.py src/skillify/agent/permissions.py`

Expected: tests pass; review each match and confirm production serialization contains only rejection/redaction logic, never sensitive values.

- [ ] **Step 7: Commit Task 2.3**

```bash
git add src/skillify/agent/permissions.py src/skillify/validator/schemas/skill-manifest-v1.schema.json src/skillify/validator/manifest.py tests/test_agent_permissions.py tests/test_validator.py
git commit -m "feat(agent): enforce local capability permissions"
```

---

### Task 2.4: Governed MCP Artifact Registry, Preview, and Offline Contract Probe

**Files:**
- Create: `src/skillify/mcp/__init__.py`
- Create: `src/skillify/mcp/registry.py`
- Create: `tests/test_mcp_registry.py`
- Create: `tests/fixtures/mcp_echo_server.py`
- Create: `tests/fixtures/mcp_filesystem_server.py`
- Create: `tests/test_mcp_remote_smoke.py`
- Modify: `src/skillify/packaging/pack.py`
- Modify: `src/skillify/publish/publisher.py`
- Test: `tests/test_packaging.py`
- Test: `tests/test_forgejo_client.py`

**Interfaces:**
- Consumes: capability lock coordinate/checksum types and `PermissionManifest` from Tasks 2.2–2.3.
- Produces: `McpTransport`, `McpArtifact`, `McpRegistry`, `McpInstallPreview`, `load_mcp_artifact()`, `render_opencode_mcp()`, and `probe_stdio_mcp()`.

- [ ] **Step 1: Write failing local/remote metadata validation tests**

```python
def test_local_mcp_requires_argv_checksum_and_intranet_source() -> None:
    artifact = local_artifact(command=("/opt/skillify/mcp/echo/bin/server",), checksum="a" * 64)
    assert load_mcp_artifact(artifact).transport is McpTransport.STDIO

@pytest.mark.parametrize("command", ["python server.py", ("sh", "-c", "server")])
def test_local_mcp_rejects_shell_commands(command) -> None:
    with pytest.raises(McpRegistryError, match="argv|shell"):
        load_mcp_artifact(local_artifact(command=command))

def test_remote_mcp_requires_https_and_auth_reference_not_secret() -> None:
    spec = load_mcp_artifact(remote_artifact(url="https://mcp.internal/mcp", auth_env="MCP_TOKEN"))
    assert render_opencode_mcp(spec)["headers"]["Authorization"] == "Bearer {env:MCP_TOKEN}"
```

Local metadata records exact version, Forgejo release/commit, archive checksum, license, absolute approved intranet URI, argv, minimal environment-name allowlist, permission manifest, and enabled default. Remote metadata records exact HTTPS URL, allowed host, auth environment reference, TLS requirement, permissions, and timeout; it never accepts a literal bearer value.

- [ ] **Step 2: Run metadata tests and record RED**

Run: `uv run --no-sync pytest -q tests/test_mcp_registry.py`

Expected: collection fails because the MCP registry package does not exist.

- [ ] **Step 3: Implement registry, OpenCode renderer, and human/machine preview**

```python
class McpRegistry:
    def register(self, artifact: McpArtifact) -> None:
        coordinate = artifact.coordinate
        if coordinate in self._artifacts and self._artifacts[coordinate] != artifact:
            raise McpRegistryError(f"conflicting MCP coordinate: {coordinate.display}")
        self._artifacts[coordinate] = artifact
    def get(self, namespace: str, name: str, version: str) -> McpArtifact:
        return self._artifacts[Coordinate(CapabilityKind.MCP, f"{namespace}/{name}", version)]
    def preview(self, artifact: McpArtifact) -> McpInstallPreview:
        return McpInstallPreview.from_artifact(artifact)

def render_opencode_mcp(artifact: McpArtifact) -> dict[str, object]:
    if artifact.transport is McpTransport.STDIO:
        return {"type": "local", "command": list(artifact.command), "enabled": artifact.enabled}
    return {"type": "remote", "url": artifact.url, "enabled": artifact.enabled,
            "headers": {"Authorization": f"Bearer {{env:{artifact.auth_env}}}"}}
```

Preview includes command executable/arguments with secret-bearing values redacted, immutable package source/checksum/license, remote domain, requested permissions, and auth reference name (never value). Registry duplicate coordinates with different contents are conflicts.

- [ ] **Step 4: Write failing bounded stdio echo/filesystem contract tests**

The fixture servers implement newline-delimited JSON-RPC for `initialize`, `tools/list`, and `tools/call`. The filesystem fixture is jailed to an injected temporary root and exposes only `read_fixture`.

```python
def test_probe_local_echo_mcp_without_shell_or_network(tmp_path: Path) -> None:
    result = probe_stdio_mcp(
        (sys.executable, str(FIXTURES / "mcp_echo_server.py")),
        request={"name": "echo", "arguments": {"text": "hello"}},
        timeout_seconds=2,
        environ={"PATH": os.environ.get("PATH", "")},
    )
    assert result.text == "hello"

def test_filesystem_fixture_cannot_escape_root(tmp_path: Path) -> None:
    result = call_filesystem_fixture(tmp_path, "../secret.txt")
    assert result.is_error is True
```

- [ ] **Step 5: Implement the probe with lifecycle cleanup and safe errors**

Launch exact argv with `shell=False`, minimal injected environment, `start_new_session=True`, pipes, byte/line limits, and monotonic deadline. Validate response IDs and JSON-RPC version. On timeout/malformed response/non-zero exit, terminate then kill the owned process group within bounded time and return/raise a stable reason code that does not include response content or environment.

- [ ] **Step 6: Add peer MCP packaging metadata and remote smoke boundary**

Extend deterministic artifact sidecar generation so `artifactKind: skill|mcp` is explicit. For MCP, include the validated MCP metadata and checksum in the sidecar; keep existing Skill archives byte-compatible unless their manifest opts into the new entrypoints schema. Publishing uses the same Forgejo immutable release/assets flow.

`tests/test_mcp_remote_smoke.py` contains exactly:

```python
pytestmark = pytest.mark.skip(reason="requires test-env: approved internal remote MCP HTTPS endpoint")
```

and a real URL/auth-reference smoke body that is unreachable unless the test environment explicitly supplies it.

- [ ] **Step 7: Run GREEN and packaging/publish regression**

Run: `uv run --no-sync pytest -q tests/test_mcp_registry.py tests/test_mcp_remote_smoke.py tests/test_packaging.py tests/test_forgejo_client.py`

Expected: offline tests pass and the single remote smoke is skipped with the exact test-env reason.

- [ ] **Step 8: Commit Task 2.4**

```bash
git add src/skillify/mcp tests/fixtures/mcp_echo_server.py tests/fixtures/mcp_filesystem_server.py tests/test_mcp_registry.py tests/test_mcp_remote_smoke.py src/skillify/packaging/pack.py src/skillify/publish/publisher.py tests/test_packaging.py tests/test_forgejo_client.py
git commit -m "feat(mcp): distribute governed mcp configurations"
```

---

### Task 2.1: OpenCode Capability Adapter and Transactional Ownership

**Files:**
- Create: `src/skillify/agent/opencode_config.py`
- Create: `tests/test_opencode_config.py`
- Modify: `src/skillify/validator/schemas/skill-manifest-v1.schema.json`
- Modify: `src/skillify/validator/manifest.py`
- Modify: `src/skillify/install/agent_defaults.py`
- Modify: `src/skillify/install/projector.py`
- Modify: `src/skillify/common/config.py`
- Test: `tests/test_projector.py`
- Test: `tests/test_validator.py`

**Interfaces:**
- Consumes: `CapabilityLockStore`, `GeneratedOwnership`, `PermissionManifest`, `summarize_permissions()`, `McpRegistry`, and `render_opencode_mcp()` from Tasks 2.2–2.4.
- Produces: `OpenCodeScopePaths`, `CapabilitySource`, `MutationKind`, `OwnedMutation`, `OpenCodeInstallPlan`, `plan_install()`, `apply_install()`, `plan_uninstall()`, `apply_uninstall()`, and `rollback_install()`.

- [ ] **Step 1: Write failing manifest entrypoint and scope-path tests**

Define one source of truth in `skill.yaml`:

```yaml
entrypoints:
  agents:
    reviewer: agents/reviewer.md
  commands:
    review: commands/review.md
  plugins:
    governed-tools: plugins/governed-tools.js
  mcp:
    repo-search: mcp/repo-search.yaml
```

Map names must match `^[a-z0-9]+(?:-[a-z0-9]+)*$`; referenced paths must be relative, remain inside the installed artifact after resolution, exist as regular files, and reject symlinks. Unknown `entrypoints` keys fail schema validation.

```python
def test_scope_paths_follow_opencode_user_and_project_layout(tmp_path: Path) -> None:
    user = OpenCodeScopePaths.user(tmp_path / "xdg-config" / "opencode")
    project = OpenCodeScopePaths.project(tmp_path / "repo")
    assert user.skills == tmp_path / "xdg-config/opencode/skills"
    assert project.skills == tmp_path / "repo/.opencode/skills"
```

- [ ] **Step 2: Run adapter tests and record RED**

Run: `uv run --no-sync pytest -q tests/test_opencode_config.py tests/test_validator.py tests/test_projector.py`

Expected: module import and strict entrypoint validation fail.

- [ ] **Step 3: Implement a pure deterministic install planner**

The planner generates these targets from the validated artifact:

- `SKILL.md` → `{scope}/skills/<manifest-name>/SKILL.md`.
- agent references → `{scope}/agents/<entry-name>.md`.
- command references → `{scope}/commands/<entry-name>.md`.
- plugin references → `{scope}/plugins/<entry-name><source-suffix>`.
- MCP references → owned `/mcp/<entry-name>` fragments in `{scope}/opencode.json`.

```python
@dataclass(frozen=True)
class OpenCodeInstallPlan:
    coordinate: Coordinate
    scope: InstallScope
    mutations: tuple[OwnedMutation, ...]
    permission_summary: PermissionSummary
    resulting_lock: CapabilityLock

def plan_install(source: CapabilitySource, *, paths: OpenCodeScopePaths,
                 lock_store: CapabilityLockStore, mcp_registry: McpRegistry,
                 installed_at: str) -> OpenCodeInstallPlan:
    manifest = source.load_validated_manifest()
    mutations = _plan_owned_mutations(source, manifest, paths, lock_store, mcp_registry)
    return OpenCodeInstallPlan(
        coordinate=source.coordinate,
        scope=paths.scope,
        mutations=tuple(sorted(mutations, key=lambda item: item.ownership_key)),
        permission_summary=summarize_permissions(source.permissions),
        resulting_lock=_lock_from_plan(source, paths.scope, mutations, installed_at),
    )
```

Sort mutations by target path and JSON pointer. A destination is writable only when absent, or when the current lock owns it and its current checksum equals the lock checksum. An unowned destination or user-modified owned target raises `OpenCodeConfigConflict`. Repeating the same plan produces only `UNCHANGED` mutations.

- [ ] **Step 4: Write failing dry-run, idempotency, conflict, and precedence tests**

```python
def test_dry_run_returns_preview_without_writes(bundle, roots) -> None:
    plan = plan_install(bundle, paths=roots.project, lock_store=roots.store,
                        mcp_registry=roots.registry, installed_at=FIXED_TIME)
    result = apply_install(plan, dry_run=True)
    assert result.changed is False
    assert not (roots.project.root / ".opencode").exists()

def test_user_and_project_installs_are_isolated_and_project_wins(bundle, roots) -> None:
    apply_install(plan_for(bundle, roots.user))
    apply_install(plan_for(bundle.with_command_body("project"), roots.project))
    assert read_command(roots.user) != read_command(roots.project)

def test_unowned_user_file_is_never_overwritten(bundle, roots) -> None:
    destination = roots.project.commands / "review.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("user-owned", encoding="utf-8")
    with pytest.raises(OpenCodeConfigConflict, match="not owned"):
        plan_install(bundle, paths=roots.project, lock_store=roots.store,
                     mcp_registry=roots.registry, installed_at=FIXED_TIME)
```

- [ ] **Step 5: Implement transactional apply and ownership-safe uninstall**

Stage whole-file writes and the merged `opencode.json` in a sibling temporary directory. Verify staged checksums, then replace targets atomically in deterministic order. If any replace fails, restore every prior byte snapshot and leave the current lock unchanged. Write the new lock only after all targets succeed.

For uninstall, delete only ownership entries in the selected lock. Whole files are deleted only if the current checksum still matches; JSON keys are removed only if their canonical fragment checksum matches. User-created sibling keys and files remain. Modified owned entries raise conflict and are preserved.

- [ ] **Step 6: Write failing update and exact rollback tests**

```python
def test_update_records_history_and_removes_only_stale_owned_entries(v1, v2, roots) -> None:
    first = apply_install(plan_for(v1, roots.project))
    second = apply_install(plan_for(v2, roots.project))
    assert second.lock.version == "2.0.0"
    assert roots.store.read_digest(first.lock.digest) == first.lock
    assert user_sibling_file(roots.project).read_text() == "keep"

def test_rollback_uses_stored_lock_and_snapshot_without_catalog(v1, v2, roots) -> None:
    first = apply_install(plan_for(v1, roots.project))
    apply_install(plan_for(v2, roots.project))
    rolled = rollback_install(first.lock.digest, paths=roots.project, lock_store=roots.store)
    assert rolled.lock.version == "1.0.0"
    assert roots.catalog.calls == 0
```

Store content snapshots by lock digest under the Skillify agent cache, mode 0700 directories/0600 files. Snapshot metadata is covered by the lock digest. Rollback verifies snapshot and lock checksums and never contacts Forgejo, devpi, public network, or the dependency resolver.

- [ ] **Step 7: Integrate existing projector without destructive replacement semantics**

Keep the legacy single-Skill projection API compatible, but route OpenCode capability installs through `opencode_config.py`. Harden `projector._project_one()` so an existing unowned target is a conflict instead of unconditional `rmtree`; existing Claude/project behavior receives regression tests. Do not silently migrate or delete legacy user directories.

- [ ] **Step 8: Run Task 2.1 GREEN and focused S2 regression**

Run: `uv run --no-sync pytest -q tests/test_opencode_config.py tests/test_capability_lock.py tests/test_agent_permissions.py tests/test_mcp_registry.py tests/test_projector.py tests/test_validator.py`

Run: `uv run --no-sync python -m compileall -q src`

Expected: all offline tests pass; no real home, Forgejo, OpenCode, MCP endpoint, or public network access.

- [ ] **Step 9: Commit Task 2.1**

```bash
git add src/skillify/agent/opencode_config.py src/skillify/validator/schemas/skill-manifest-v1.schema.json src/skillify/validator/manifest.py src/skillify/install/agent_defaults.py src/skillify/install/projector.py src/skillify/common/config.py tests/test_opencode_config.py tests/test_projector.py tests/test_validator.py
git commit -m "feat(agent): install skillify capabilities into opencode"
```

---

### G2 Development Gate: Combined Offline Acceptance and Stage Review

**Files:**
- Create: `tests/test_s2_capability_distribution.py`
- Create: `docs/deployment/capability-distribution.md`
- Modify: `docs/2026-07-16-endpoint-agent-tasks.md`

- [ ] **Step 1: Add a failing end-to-end offline fixture**

Build a deterministic Workflow Pack fixture containing one Skill, one agent, one command, one plugin, and one local echo MCP. Resolve it from fake immutable release metadata, preview permissions/source/network/commands, install to project scope, repeat idempotently, update, roll back by stored digest, and uninstall. Assert a pre-existing user command and unrelated `opencode.json` key survive every operation.

- [ ] **Step 2: Run the G2 fixture and close integration gaps**

Run: `uv run --no-sync pytest -q tests/test_s2_capability_distribution.py`

Expected RED: the first run exposes any missing cross-task orchestration. Apply the smallest fixes in the owning S2 module, add focused regression tests, and rerun until GREEN.

- [ ] **Step 3: Document operator flow and honest test-env boundary**

Document preview/install/update/rollback/uninstall, user/project precedence, ownership conflicts, audit location/redaction, local MCP argv/source/checksum, and recovery from an interrupted transaction. Mark these as `[test-env]`: real OpenCode loading all generated definitions, real Forgejo checksum, approved internal remote MCP HTTPS smoke, and endpoint confirmation interaction.

- [ ] **Step 4: Run S2 Dev-DoD and baseline comparison**

Run focused S2 tests plus all S1 contract tests, then backend tests in reliable sub-25-second file partitions if the execution harness truncates a monolithic run. Run:

```bash
uv run --no-sync python -m compileall -q src
cd web && npm run type-check
cd web && npm test
cd web && npm run build
git diff --check
```

Expected baselines remain separately recorded: `tests/test_projector.py::test_project_uses_symlink_when_forced` may fail on this macOS host, and `web/tests/appFooter.spec.js` has one existing quick-links failure. S2 must not add a failure or claim either baseline as new.

- [ ] **Step 5: Independent whole-S2 review**

Review the complete S2 range for upstream coverage, lock reproducibility, dependency/cycle/missing/tamper behavior, deny dominance, secret/path redaction, ownership safety, atomic rollback, no runtime public download, no shell execution, and no server-side MCP process. Fix every Critical/Important finding and repeat review until Approved.

- [ ] **Step 6: Commit gate evidence and push after controller verification**

```bash
git add tests/test_s2_capability_distribution.py docs/deployment/capability-distribution.md docs/2026-07-16-endpoint-agent-tasks.md
git commit -m "test(agent): verify offline capability distribution gate"
git push origin main
```

The target-only G2 remains pending until a real approved Linux/OpenCode/Forgejo/internal-MCP environment demonstrates offline install/update/rollback without modifying user-owned configuration.

## Plan Self-Review

- Spec coverage: Tasks 2.1–2.4 and Dev/test-env G2 each map to an implementation section and exact tests.
- Source of truth: `skill.yaml` plus immutable peer artifact sidecars feed generated OpenCode configuration; no second hand-maintained capability catalog is introduced.
- Type consistency: Task 2.1 consumes the exact lock, permission, and MCP interfaces produced by Tasks 2.2–2.4.
- Safety: no step authorizes real-home reads, shell commands, public runtime downloads, plaintext auth, destructive unowned overwrite, dependency resolution during rollback, or server-side execution.
- Scope: no Code Map, Workflow Pack content, control-plane DB, device identity, Web UI, or S3+ implementation is pulled into S2.
- Placeholder scan: the plan contains no deferred implementation placeholders; real-environment evidence is explicitly classified as `[test-env]`.
