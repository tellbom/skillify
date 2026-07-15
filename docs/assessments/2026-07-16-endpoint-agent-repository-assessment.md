# Endpoint Agent Repository Assessment

**Date:** 2026-07-16

**Scope:** G0 / Task 0.1, documentation only

**Repository:** `/Users/fuziqiang/Desktop/skillify` at `9c8fd0e5c569ebeb8d005f436780994c5af66024` on `main`
**Verdict:** **GO for S1 offline development after this assessment and its S1 plan are reviewed.** Real OpenCode, target-Linux, model-endpoint, Forgejo, devpi, DM8, and Keycloak acceptance remains `[test-env]`; this document does not claim G1 acceptance.

## 1. Evidence and method

The worktree was clean before this documentation task. The assessment used `git ls-files`, `rg --files`, the required keyword search, direct inspection of the CLI/config/install/telemetry/test modules, `git log`, and the baseline supplied by Task 0.1. The full slow suites were not rerun because the brief already records their 2026-07-16 output and explicitly permits focused read-only verification.

Local tool facts captured during assessment:

```text
Python 3.13.2
uv 0.11.28 (ebf0f43d7 2026-07-07 x86_64-apple-darwin)
node v20.10.0
npm 10.2.3
branch main
HEAD 9c8fd0e5c569ebeb8d005f436780994c5af66024
tracked files 300
```

The development host is macOS/x86_64, not a target Linux endpoint. No target OpenCode, internal model endpoint, Forgejo, devpi, DM8, Keycloak, or target Linux host is available here.

## 2. Repository inventory

### 2.1 Tracked-file distribution

This inventory is pinned to the pre-assessment baseline commit
`9c8fd0e5c569ebeb8d005f436780994c5af66024`. It is reproducible and complete:

```bash
git ls-tree -r --name-only 9c8fd0e5c569ebeb8d005f436780994c5af66024
git ls-tree -r --name-only 9c8fd0e5c569ebeb8d005f436780994c5af66024 | wc -l
git ls-tree -r --name-only 9c8fd0e5c569ebeb8d005f436780994c5af66024 | sha256sum
git ls-tree -r --name-only 9c8fd0e5c569ebeb8d005f436780994c5af66024 |
  awk -F/ '{count[$1]++} END {for (area in count) print area, count[area]}' | sort
```

Expected evidence:

```text
tracked files: 300
sorted path-stream SHA-256: 641d7b65372f54eac38446634fb757d339cb5e73955ba5b627034828ad7c5e56
.gitignore 1
Dockerfile 1
PLAN.md 1
README.md 1
TASKS.md 1
docs 41
examples 10
infra 10
pyproject.toml 1
scripts 2
spec 2
src 71
tests 45
uv.lock 1
web 112
```

The first command is the full tracked-file inventory artifact: it prints every
path in the audited tree, not a working-directory glob. The count, digest, and
area totals make omissions or later drift detectable without copying a stale
300-line path list into this assessment. The two Task 0.1 documents are absent
from that baseline by definition and are the only files added by commit
`72015d49a4699656a9e4ca242ebf5cadeda489ee`.

| Top-level area | Tracked files | Relevant responsibility |
| --- | ---: | --- |
| `src/` | 71 | Python CLI, installer, publisher, index, web, webhook, validation |
| `tests/` | 45 | pytest unit/integration tests and fake Forgejo/Keycloak services |
| `web/` | 112 | Vue 3/Vite UI and Vitest tests |
| `docs/` | 41 | plans, reviews, deployment, operations, testing |
| `infra/` | 10 | Compose, DM8 SQL, devpi image, environment sample |
| `examples/` | 10 | text and spreadsheet Skill fixtures |
| `spec/` | 2 | Skill manifest v1 schema and prose specification |
| root metadata/scripts | 9 | `pyproject.toml`, `uv.lock`, Dockerfile, plans, README, scripts |
| **Total** | **300** | `git ls-files` result |

### 2.2 Execution and distribution paths

| Concern | Existing real paths | Finding |
| --- | --- | --- |
| CLI entry point | `src/skillify/cli/main.py`; `[project.scripts] skillctl` in `pyproject.toml` | Typer is the single user-facing CLI; extend it with an `agent` group. |
| Configuration | `src/skillify/common/config.py` | One `~/.skillify` home today; no XDG-separated agent config/state/cache/log roots. |
| Environment checks | `src/skillify/cli/doctor_cmd.py`, `tests/test_cli_doctor.py` | Existing injectable config and local fake HTTP tests are reusable; checks are Forgejo/devpi/agent-directory oriented. |
| Skill projection | `src/skillify/install/agent_defaults.py`, `src/skillify/install/projector.py`, `tests/test_projector.py` | OpenCode is only a Skill projection target; this is not a Provider or execution adapter. Reuse later for S2, not as the S1 runtime. |
| Immutable artifacts | `src/skillify/packaging/pack.py`, `src/skillify/publish/publisher.py`, `src/skillify/publish/forgejo_client.py` | Forgejo Release plus checksum is the authoritative Skill flow and must remain unchanged. |
| Checksum and safe extraction | `src/skillify/install/extract.py`, `tests/test_installer.py` | `sha256_file` and `verify_checksum` are suitable for OpenCode offline artifacts; safe extraction rejects traversal, links, and devices. |
| Per-Skill dependency isolation | `src/skillify/install/venv.py`, `src/skillify/install/dependencies.py`, `tests/test_venv_offline.py` | Preserve per-Skill `uv` venv and devpi. OpenCode itself is a separately governed binary, not a Skill Python dependency. |
| Local locks | `src/skillify/install/lock.py` | Skill lock schema is domain-specific; reuse conventions, not the `SkillLock` type, for OpenCode compatibility metadata. |
| HTTP test seam | `tests/test_cli_doctor.py`, `tests/test_installer.py`, `tests/fake_forgejo.py` | Standard-library localhost HTTP servers already provide the repository-consistent offline test pattern. |
| Telemetry privacy | `src/skillify/common/telemetry.py`, `tests/test_telemetry.py` | Reporting is opt-in and schema-limited. S1 events need their own safe allowlist but must preserve the same default-off posture. |
| Database | `src/skillify/index/`, `infra/dm8-init/` | S1 has no database dependency; tests must not require DM8. |
| Frontend | `web/` | S1 makes no frontend changes. Existing frontend failures are unrelated and remain baseline debt. |

### 2.3 Required full-repository keyword search

The required search was run across every tracked text file at the same baseline
commit, including root files, docs, examples, infra, source, tests, lockfiles,
and web content. These commands are independently auditable and print the exact
matching path set for each term:

```bash
for term in skillctl agent opencode claude mcp orchestration runtime permissions devpi Forgejo; do
  git grep -I -i -l -e "$term" 9c8fd0e5c569ebeb8d005f436780994c5af66024 -- .
done
```

The `src/` + `tests/` column is retained only to distinguish executable/test
evidence from planning and deployment references.

| Keyword | All tracked files | `src/` + `tests/` | What exists | S1 conclusion |
| --- | ---: | ---: | --- | --- |
| `skillctl` | 54 | 27 | CLI, docs, deployment and tests | Extend the existing entry point. |
| `agent` | 76 | 33 | Mostly plans, Skill projection and comments | No execution contract; add `skillify.agent`. |
| `opencode` | 22 | 8 | Plans plus projection defaults/doctor/tests | Projection only; Provider is new. |
| `claude` | 55 | 26 | Plans, target defaults and fixtures | Do not build a Claude Code Provider before G1 `[test-env]`. |
| `mcp` | 9 | 0 | Documentation/planning references only | No Python MCP implementation; S1 does not create one. |
| `orchestration` | 25 | 10 | Plans and manifest/index passthrough | No engine; do not add one in S1. |
| `runtime` | 44 | 17 | Plans, manifest validation and web build data | No endpoint execution runtime. |
| `permissions` | 23 | 5 | Plans and manifest/build validation | No local merger; S1 enforces workspace allowlisting. |
| `devpi` | 41 | 11 | Deployment docs/config/doctor/install tests | Preserve; no public package runtime access. |
| `Forgejo` | 93 | 53 | Artifact chain, deployment, index, webhook, fakes | Preserve; endpoint execution stays local. |

Additional focused search found no `provider` or `mcp` implementation under `src/`/`tests/`. The S1 Provider contract is therefore a genuinely new boundary, while a second CLI, second installer, private Agent loop, or private MCP client would overlap existing or upstream responsibilities and is rejected.

### 2.4 Recent repository history

```text
9c8fd0e 2026-07-16 建立改造计划
ba3a598 2026-07-15 完成分类改造
decef94 2026-07-15 docs: plan primary skill categories
cc5c0d7 2026-07-15 docs: design primary skill categories
a49a026 2026-07-14 修正参考样式
f0d14ba 2026-07-14 docs: design structured skill md editor
1acaa38 2026-07-14 代码修正，准备正式进入上线评估
912f74d 2026-07-14 feat: expose skill list community metrics
```

The latest commit added the endpoint-agent master plan, execution contract, and task board. It did not add Provider functionality.

## 3. Reuse matrix and design decisions

| S1 requirement | Reuse | Gap | Decision |
| --- | --- | --- | --- |
| `skillctl agent` command group | `src/skillify/cli/main.py`, Typer, Rich consoles, `CliRunner` tests | No command group or stable agent error codes | Add one Typer sub-app in `src/skillify/cli/agent_cmd.py`; do not add another executable. |
| XDG paths | `SkillifyConfig`, `SKILLIFY_HOME` compatibility | Agent config/state/cache/log are not separated | Add `AgentPaths` and XDG resolution to `common/config.py`; keep existing Skill paths backward compatible. |
| Workspace authorization | `Path` use and temporary-directory tests | No endpoint workspace registry | Store explicit resolved workspace entries in agent config; reject parents/siblings and never scan the machine. |
| Provider abstraction | None | Entire contract absent | Add synchronous Python Protocol plus explicit dataclasses/enums and a deterministic `FakeProvider`. |
| Event privacy | Default-off telemetry and payload-key assertions | No TaskEvent schema | Add allowlisted event details. Raw prompt, source text, secrets, environment, database results, and raw tool output never enter `TaskEvent`. |
| OpenCode control | Existing `requests`; official OpenCode HTTP/OpenAPI and SSE | No process or API adapter | Use the official Server/OpenAPI directly from Python. Do not parse TTY text and do not add a Node sidecar solely for the JS SDK. |
| Process lifecycle | Python stdlib subprocess in `install/venv.py` | No injectable process-group manager | Add injected process/http/clock/port/password seams in `providers/opencode.py`; use a new process session/group and bounded cleanup. |
| Offline HTTP tests | Local standard-library fake servers | No OpenCode fixture | Add a fake OpenCode HTTP/SSE server in the focused Provider contract test. |
| Integrity verification | `install/extract.py` SHA-256 helpers | No OpenCode distribution manifest | Reuse checksum helper; add an OpenCode-specific schema/selector because `SkillLock` fields do not model OS/libc/CPU. |
| Compatibility diagnostics | Existing `CheckResult`/doctor output | No manifest-driven version/platform check | Extend `doctor_cmd.py` to consume a configured/pinned manifest and compare actual version/platform. |
| Offline docs | `docs/deployment/`, `infra/` conventions | No OpenCode offline runbook | Add one deployment runbook and one canonical manifest. Never recommend `curl | sh`. |

### Official integration findings

- The official [OpenCode Server documentation](https://opencode.ai/docs/server/) states that `opencode serve` exposes OpenAPI 3.1 at `/doc`, SSE at `/event`, health/version at `/global/health`, session creation/abort APIs, defaults to `127.0.0.1`, and supports Basic Auth through `OPENCODE_SERVER_PASSWORD`.
- The official [OpenCode SDK documentation](https://opencode.ai/docs/sdk/) describes a type-safe JS/TS SDK generated from the OpenAPI specification. Skillify is Python and already depends on `requests`; direct use of the documented OpenAPI avoids a cross-language sidecar and does not change `skillctl`'s implementation language.
- The official [CLI documentation](https://opencode.ai/docs/cli/) documents `serve`, `--hostname`, `--port`, `OPENCODE_CONFIG_DIR`, `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_DISABLE_LSP_DOWNLOAD`, `OPENCODE_SERVER_PASSWORD`, and `OPENCODE_MODELS_URL`. S1 must set the offline-safe controls explicitly rather than rely on user defaults.
- The official [network documentation](https://opencode.ai/docs/network/) requires `NO_PROXY=localhost,127.0.0.1` when proxies are set. S1 must preserve this localhost bypass without copying arbitrary environment variables into telemetry or logs.
- OpenCode event payloads can contain prompts, deltas, commands, tool inputs, and tool outputs. The Provider must map event kinds to safe summaries and discard those raw fields, rather than forwarding upstream payloads wholesale.

## 4. Real S1 file map

Every path is either present now or explicitly marked **new**.

### Task 1.1 — CLI command surface

| Action | Path | Responsibility |
| --- | --- | --- |
| Modify (existing) | `src/skillify/cli/main.py` | Register the `agent` Typer sub-app. |
| Modify (existing) | `src/skillify/common/config.py` | Add XDG-separated agent paths and explicit workspace configuration. |
| Create (new) | `src/skillify/cli/agent_cmd.py` | `doctor/init/run/status/stop/logs`, stable JSON error envelope, injectable service boundary. |
| Create (new) | `tests/test_cli_agent.py` | Parsing/help snapshots, exit codes, offline/no-server branches, workspace rejection, XDG isolation. |

### Task 1.2 — Provider Adapter contract

| Action | Path | Responsibility |
| --- | --- | --- |
| Create (new) | `src/skillify/agent/__init__.py` | Export the public contract types. |
| Create (new) | `src/skillify/agent/provider.py` | `AgentProvider` Protocol and explicit probe/start/task/handle/session/result types. |
| Create (new) | `src/skillify/agent/events.py` | State/event enums, protocol version 1, safe event serialization. |
| Create (new) | `src/skillify/agent/fake_provider.py` | Deterministic offline lifecycle implementation. |
| Create (new) | `tests/test_provider_contract.py` | Startup/order/cancel/failure/cleanup/privacy contract. |

### Task 1.3 — OpenCode Provider

| Action | Path | Responsibility |
| --- | --- | --- |
| Create (new) | `src/skillify/agent/providers/__init__.py` | Provider package export. |
| Create (new) | `src/skillify/agent/providers/opencode.py` | Official HTTP/OpenAPI/SSE mapping and bounded local process lifecycle. |
| Modify (new from Task 1.1) | `src/skillify/cli/agent_cmd.py` | Wire the default local service to `OpenCodeProvider` without server dependency. |
| Create (new) | `tests/test_opencode_provider_contract.py` | Fake HTTP/SSE normal/cancel/timeout/crash/SIGTERM branches and secret/log assertions. |
| Create (new) | `tests/test_opencode_provider_smoke.py` | Default-skipped real binary test with `requires test-env:` reason. |

### Task 1.4 — Offline distribution and compatibility lock

| Action | Path | Responsibility |
| --- | --- | --- |
| Modify (existing) | `src/skillify/cli/doctor_cmd.py` | OS/arch/libc/version/manifest checks; keep existing checks intact. |
| Modify (existing) | `src/skillify/common/config.py` | Add configured offline manifest/artifact paths and environment overrides. |
| Create (new) | `src/skillify/install/opencode_distribution.py` | Manifest schema validation, deterministic selection, SHA-256 verification, compatibility result. |
| Create (new) | `infra/offline/opencode-manifest.json` | Canonical pinned version/platform/license/source/checksum/intranet-location matrix. |
| Create (new) | `tests/test_opencode_distribution.py` | Schema, selection, corruption, no-floating-version, doctor integration. |
| Create (new) | `docs/deployment/offline-opencode.md` | Mirror, install, verify, upgrade/downgrade, rollback and `[test-env]` runbook. |

No S1 task needs a frontend, DM8, Forgejo, devpi, Keycloak, MCP implementation, orchestration engine, alternate CLI, or Claude Code Provider file.

## 5. Test baseline

These are the raw results already observed on 2026-07-16 and supplied by the Task 0.1 brief. They predate S1 code and must not be attributed to it.

### 5.1 Backend

Exact dependency sync and exact backend commands are blocked on this macOS host because unconditional `dmpython==2.5.32` has no macOS wheel:

```text
uv sync
uv run python -m compileall -q src
uv run pytest -q
```

Assessment fallback environment:

```bash
uv sync --no-install-package dmpython --no-install-package dmsqlalchemy
uv run --no-sync python -m compileall -q src
uv run --no-sync pytest -q
```

Observed result:

```text
compileall: PASS
pytest: 319 passed, 1 failed, 1 skipped, 2 warnings in 144.01s
FAILED tests/test_projector.py::test_project_uses_symlink_when_forced
expected a symlink but resolved the installed skill directory
```

The single skip is existing. Any S1 test that needs a real OpenCode/model/MCP service must be skipped by default with `pytest.mark.skip(reason="requires test-env: real OpenCode binary, model endpoint, MCP runtime, and target Linux")`.

### 5.2 Frontend

```text
cd web && npm run type-check
PASS

cd web && npm test
165 passed, 1 failed across 18 files
FAILED tests/appFooter.spec.js > AppFooter > renders authorized leaf routes as quick links
expected two links but found zero

cd web && npm run build
PASS with existing Vite dynamic/static import and large-chunk warnings
```

`npm ci` emitted existing engine warnings because the host runs Node `v20.10.0` while current `chokidar`/`readdirp` packages require `>=20.19.0`.

### 5.3 S1 admission rule

Until the unconditional DM driver issue is resolved, macOS development uses the documented `--no-install-package`/`--no-sync` fallback. Each S1 commit must run its focused offline tests plus fallback compileall. Full-suite output is compared to this baseline: the two named existing failures may remain, but no new failure is accepted. S1 has no frontend files, so frontend commands are final regression evidence rather than per-step RED/GREEN commands.

## 6. Offline-testability assessment

| Module/behavior | Offline seam | Fully testable now? | Deferred evidence |
| --- | --- | --- | --- |
| CLI parsing/help/error JSON | Typer `CliRunner`, injected service | Yes | None |
| XDG path selection | Explicit environment mapping and `tmp_path` | Yes | None |
| Workspace authorization | Resolved temporary paths | Yes | Filesystem ACL differences `[test-env]` |
| Provider states/events | `FakeProvider`, injected UTC clock/IDs | Yes | None |
| OpenCode HTTP mapping | Fake localhost HTTP/SSE server | Yes | Exact real-version behavior `[test-env]` |
| Process launch arguments/env | Injected `Popen` factory and port/password factories | Yes | Real binding/process tree `[test-env]` |
| Cancellation/timeout/crash/SIGTERM | Fake process + fake transport | Yes | Kernel/process-group behavior `[test-env]` |
| Secret/log privacy | Capturing logger, temp config tree, event serialization | Yes | Real OpenCode's own log contents `[test-env]` |
| Manifest validation/selection | Dict/JSON fixtures | Yes | Approved intranet artifact inventory `[test-env]` |
| Artifact checksum/corruption | Temporary files and existing SHA-256 helper | Yes | Download/mirror transport `[test-env]` |
| Linux libc/CPU selection | Injected platform detector | Logic yes | Binary execution on each target `[test-env]` |
| Internal model endpoint | Fake health response only | Contract branch yes | Real inference/tool calls `[test-env]` |
| MCP probe | Fake `/mcp` response only | Contract branch yes | Approved MCP runtime `[test-env]` |

The plan must inject time, IDs, process creation, port selection, password generation, HTTP transport, and platform detection. Code that reaches a public network, real home directory, real OpenCode, or real server during default tests is a design failure.

## 7. Linux/OpenCode offline compatibility draft

OpenCode is pinned here to **v1.15.11** as the S1 candidate, not to `latest`. The official [v1.15.11 release](https://github.com/anomalyco/opencode/releases/tag/v1.15.11) was published 2026-05-27. Its [package metadata](https://github.com/anomalyco/opencode/blob/v1.15.11/packages/opencode/package.json) and [LICENSE](https://github.com/anomalyco/opencode/blob/v1.15.11/LICENSE) identify version `1.15.11` and MIT licensing. GitHub's release API supplies SHA-256 digests for the assets below.

| Draft target | Official asset | Official SHA-256 | Admission |
| --- | --- | --- | --- |
| Linux x86_64, glibc, AVX2-capable | `opencode-linux-x64.tar.gz` | `49317253722c698394980e1921ff28e919d79bb29d5c3f4cf314a4adaf7037cd` | `[test-env]` execute and smoke |
| Linux x86_64, glibc, baseline CPU | `opencode-linux-x64-baseline.tar.gz` | `eb19eabc9cb7fa8a73898328b69720738d35e0cad716898bfdbc2547f88b2450` | Preferred CentOS 7/unknown-CPU candidate; `[test-env]` glibc check |
| Linux x86_64, musl, AVX2-capable | `opencode-linux-x64-musl.tar.gz` | `82fdc56334a02fd89b123643197b59bea2af829be13f82ec154f210053423207` | `[test-env]` Alpine smoke |
| Linux x86_64, musl, baseline CPU | `opencode-linux-x64-baseline-musl.tar.gz` | `421a63ecc5ae66b87b150349f29477a952a01526e85b48783bccce4c7b8dabd9` | `[test-env]` Alpine/older CPU smoke |
| Linux aarch64, glibc | `opencode-linux-arm64.tar.gz` | `93e4399f308c49387c25ec2b570602bf0f9dd5f57989427946c0c28dbf259ff4` | `[test-env]` execute and smoke |
| Linux aarch64, musl | `opencode-linux-arm64-musl.tar.gz` | `871b80411bd670ed9372335f0658203557fa4bfbf7791a3b1ab1d1f641103448` | `[test-env]` execute and smoke |

The upstream build matrix distinguishes glibc/musl and baseline x64, but the official public material inspected does not state a minimum glibc version or a supported distribution list. Therefore **CentOS 7 is not approved by this assessment**. Test `ldd --version`, `uname -m`, CPU flags, `opencode --version`, a localhost-only provider run, and cleanup on the real target. If the baseline glibc binary fails, the acceptable paths are a supported newer enterprise distribution or an approved musl bundle; silently bypassing the gate is not acceptable.

Offline installation draft:

1. Security/OSS review approves the exact version and license.
2. A connected staging machine downloads the exact GitHub Release asset; no `curl | sh` is used.
3. Verify the GitHub release digest, malware scan the archive, and publish it as an immutable intranet artifact.
4. Record the intranet URI and its independently recomputed SHA-256 in `infra/offline/opencode-manifest.json`.
5. The target selects by exact version/OS/arch/libc/CPU, verifies SHA-256 before extraction, and installs without public network access.
6. Set `OPENCODE_DISABLE_AUTOUPDATE=true`, `OPENCODE_DISABLE_LSP_DOWNLOAD=true`, `autoupdate:false`, explicit internal model configuration, and `NO_PROXY=localhost,127.0.0.1`.
7. `[test-env]` perform disconnected install, upgrade, downgrade, rollback, real task, localhost socket inspection, and residual-process inspection.

## 8. Dependency, license, and security approval findings

### 8.1 Dependency decision

- S1 does **not** need a new Python runtime dependency. Existing `requests>=2.31` covers bounded HTTP and streaming SSE; stdlib covers processes, sockets, secrets, JSON, hashing, signals, and temporary directories.
- The official `@opencode-ai/sdk` v1.15.11 is MIT but is JS/TS. Adding Node as an endpoint runtime dependency or inventing a bridge would increase the offline supply-chain surface without improving access to the same generated OpenAPI types, so it is not selected for S1.
- The selected OpenCode binary is an external governed runtime artifact, not a `pyproject.toml` dependency. `pyproject.toml` therefore remains unchanged in the S1 plan unless implementation evidence proves `requests` cannot meet the pinned API contract.
- Existing Python minimum ranges are reproducibly locked by `uv.lock`, while the unconditional DM packages currently prevent exact macOS sync. This is pre-existing and must not be worked around in production packaging by dropping DM support.

### 8.2 License and provenance

| Component | Candidate | License/source | Finding |
| --- | --- | --- | --- |
| OpenCode CLI/server | v1.15.11 | MIT; official `anomalyco/opencode` tag/release | Technically acceptable for review; final internal OSS approval and notice retention required. |
| OpenCode JS SDK | v1.15.11 | MIT; official package metadata | Reviewed but not selected for Python S1. |
| Python HTTP/process stack | existing repository dependencies/stdlib | Existing approvals | Reuse; no new OSS request. |

The manifest must contain `version`, `skillctlVersion`, `os`, `arch`, `libc`, `cpu`, `sha256`, `license`, `sourceUrl`, and `intranetUri`. `sourceUrl` is provenance only; runtime installers must use `intranetUri` and must reject an empty or public-internet runtime location.

### 8.3 Security conditions before G1

- Bind only `127.0.0.1`; never `0.0.0.0`; disable mDNS; use an unpredictable per-process Basic Auth password held in memory/environment only.
- Pass a minimal allowlisted subprocess environment. Do not log environment mappings, Authorization headers, prompt text, source content, tool input/output, model keys, or the generated password.
- OpenCode documents that it can load credentials/environment and project `.env` data. S1 cannot claim those files are absent. The Provider must prevent them from entering Skillify events/logs, and `[test-env]` must inspect OpenCode's own configured logs and config/data roots.
- Use explicit resolved workspace and allowed paths. Refuse `/`, the home directory root, non-existent paths, symlink escapes, and any workspace not registered by `agent init`.
- Keep execution local. No Skillify server path access, inbound endpoint listener, prompt/source upload, or implicit public model/package/plugin/update lookup is permitted.
- Internal security must approve the OpenCode binary, exact model endpoint/provider configuration, archive mirror, retained MIT notice, and the operating-system support matrix before production use.

## 9. P0 readiness blockers and non-blockers

| Finding | S1 offline development | G1/production effect |
| --- | --- | --- |
| Target Linux distribution/glibc/CPU is not selected or available | Not a blocker to contract/TDD work | **Blocker** to real OpenCode acceptance. |
| No approved intranet OpenCode artifact URI or security scan record | Manifest logic can use fixtures | **Blocker** to disconnected install. |
| No real internal model endpoint/OpenCode configuration | Fake contract remains testable | **Blocker** to end-to-end task acceptance. |
| Exact backend sync blocked on macOS by DM wheels | Focused fallback commands are available | Packaging/CI must run on a supported platform; do not call macOS exact suite green. |
| Existing backend projector test failure | Unrelated baseline | Must not increase; fix separately. |
| Existing frontend footer test failure and Node engine warning | S1 has no frontend changes | Must not be attributed to S1; resolve before a clean product release. |
| No Alembic baseline/confirmed DM8 migration path found | S1 is local and DB-free | Production control-plane readiness blocker, not S1 Provider blocker. |
| Real Forgejo/devpi/DM8/Keycloak recovery and closed-loop checks remain `[test-env]` | Fakes/SQLite/temp dirs cover S1 | Blocks broader production rollout, not local G1 Provider design. |
| OpenCode event/API compatibility can change between releases | Pin v1.15.11 fixtures | Version upgrade requires manifest + contract test update and `[test-env]` smoke. |

The repository's P0 platform-readiness work should continue in parallel, but it must not expand S1 into server execution, database work, or a second CLI.

## 10. ADR handoff draft

Task 0.2 should formalize these decisions without changing their meaning:

1. Extend `skillctl`; do not create an overlapping CLI or change its Python implementation language.
2. OpenCode first behind a Provider Adapter; do not implement a Claude Code Provider before G1 `[test-env]` passes and real demand exists.
3. Agent execution is local; the server is control plane only; endpoint connectivity is outbound and the server never accesses local paths.
4. Preserve OpenCode's Agent loop and native file/Shell/Git/test tools; MCP remains for external/reusable integrations rather than wrapping all local tools.
5. `task_protocol_version: 1`.
6. `provider_contract_version: 1`.

## 11. G0 checklist

- [x] Real repository inventory and required keyword matrix.
- [x] Reuse matrix and evidence for genuinely new components.
- [x] Real per-task Create/Modify/Test file map for Tasks 1.1–1.4.
- [x] Raw backend/frontend baseline with old failures separated from new work.
- [x] Offline-testability assessment with injected Fake/temp/clock/process/network seams.
- [x] Linux/OpenCode compatibility and offline-install draft, with target-only claims marked `[test-env]`.
- [x] Dependency/license/security findings and P0 readiness blockers.
- [x] Precise S1 TDD plan at `docs/superpowers/plans/2026-07-16-s1-opencode-provider.md`.

**Assessment outcome:** the repository is ready to begin S1 offline TDD after review of the companion plan. G1 remains unearned until every `[test-env]` item is executed on an approved Linux/OpenCode/model environment.
