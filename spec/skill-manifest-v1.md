# Skillify Skill Manifest — v1

> Status: implemented (T0.1). Companion machine-readable schema: `skill-manifest-v1.schema.json`.
> Consumed by: `skillctl validate`, packager (T1.2), publisher (T1.3), installer (T1.4), web index (M3).

## 1. Scope

Every skill published to Skillify has a `skill.yaml` at its root. This document is the
authoritative field list for `manifestVersion: 1`. Breaking changes to required fields or
semantics require bumping `manifestVersion` and adding a migration path — this file is not
allowed to change meaning out from under an existing `manifestVersion`.

## 2. Directory layout

```
<namespace>/<name>/
  SKILL.md            # Claude Agent Skill main file (YAML frontmatter: name, description, ...)
  skill.yaml           # this manifest
  scripts/              # optional: python / shell scripts
  requirements.txt      # optional: present iff dependencies.python is non-empty
  resources/            # optional: static assets
  README.md              # optional but recommended
```

`namespace/name` is the globally unique identifier used everywhere else in the system
(Forgejo repo path, neutral install dir `~/.skillify/skills/<namespace>/<name>`,
CLI args like `skillctl install <namespace>/<name>`).

## 3. Fields

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `manifestVersion` | integer | yes | Must be `1` for this spec. |
| `namespace` | string | yes | `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`, must match the parent directory / Forgejo org segment. |
| `name` | string | yes | Same pattern as `namespace`, must match the skill directory name. |
| `version` | string | yes | Strict [SemVer 2.0.0](https://semver.org). |
| `description` | string | yes | 1–500 chars, one paragraph, no markdown. |
| `author` | string \| object | yes | Either a display string, or `{name, email?}`. |
| `license` | string | yes | SPDX identifier (e.g. `MIT`, `Apache-2.0`). |
| `runtime` | enum | yes | `claude-agent-skill` \| `custom`. Determines which adapter/loader is used. |
| `targets` | array\<enum\> | yes | ≥1 of `claude`, `opencode`, `codex`, `aider`, `project`. What agent adapters this skill is projected into by default. |
| `dependencies.python` | array\<string\> | no | PEP 508 requirement strings, resolved against the configured index (devpi in prod). Default `[]`. |
| `dependencies.system` | array\<string\> | no | Declared system binaries/tools the skill shells out to (informational — used by `doctor` / review, not auto-installed). Default `[]`. |
| `dependencies.skills` | array\<string\> | no | Other skills this one depends on, `"namespace/name@semver-range"`. Default `[]`. |
| `entrypoints` | object | no | Free-form in v1 (e.g. `{main: scripts/run.py}`); validated structurally per-`runtime` starting v2. Default `{}`. |
| `permissions` | array\<string\> | no | Declared capabilities (network, filesystem, shell, etc.) for review/audit. Default `[]`. |
| `tags` | array\<string\> | no | Free-form search/index tags, surfaced by the web index (T2.2/T3.1). Default `[]`. |
| `orchestration` | object | no | Reserved for future multi-agent orchestration hooks (T6.3). Free-form, unvalidated in v1 beyond "must be an object". |
| `reporting` | object | no | `{enabled: bool}`. Reserved for client→server run reporting (T6.2). Default `{enabled: false}`. |

Unknown top-level fields are rejected (`additionalProperties: false`) — this keeps the format
honest about what's actually load-bearing; new fields require a documented addition here first.

### 3.1 Fields added beyond the PLAN.md §3 sketch (implementation-time decisions)

PLAN.md's example `skill.yaml` did not spell out every field needed to make the directory
layout (`skills/<namespace>/<name>/`) and the later indexing task (T2.2, which needs `tags`)
actually work. Two fields were added while implementing T0.1; both are additive, not in
conflict with any decision recorded in PLAN.md §0/§6/§7:

- **`namespace`** — required because the neutral install path and CLI addressing
  (`skillctl install <namespace>/<name>`, PLAN.md §4) are namespaced, but the manifest sketch
  only had a flat `name`. Without it, the manifest can't self-describe its own install path.
- **`tags`** — required because T2.2 ("写 PostgreSQL 索引表(name/version/desc/author/tags/checksum/时间)")
  names `tags` as an indexed column, but no manifest field carried it.

If either of these turns out to be wrong (e.g. namespace should be derived purely from the
Forgejo org and never duplicated in-file), that's a spec-level call for Opus review, not
something to silently change downstream — flagging here per the joint-review request.

## 4. Validation rules (enforced by `skillctl validate` / T0.2)

1. `skill.yaml` parses as YAML and matches `skill-manifest-v1.schema.json` (JSON Schema
   2020-12, `additionalProperties: false` everywhere).
2. `manifestVersion == 1`.
3. `namespace` and `name` match the immediate parent directory names on disk
   (`<parent>/<namespace>/<name>/skill.yaml`) when validated in a namespace-aware context;
   in a standalone context (single skill dir passed to `validate <dir>`) only the directory's
   own basename is checked against `name`.
4. `version` is valid SemVer 2.0.0.
5. `SKILL.md` exists, has YAML frontmatter, and frontmatter `name`/`description` are present
   and non-empty.
6. If `dependencies.python` is non-empty, `requirements.txt` **or** `pyproject.toml` must
   exist at the skill root.
7. Each `dependencies.skills` entry matches `^[a-z0-9-]+/[a-z0-9-]+@.+$` and the version
   range after `@` is a syntactically valid PEP 440 / semver range (best-effort check).
8. `runtime: claude-agent-skill` requires `targets` to include `claude` (a Claude Agent
   Skill that isn't projected to Claude is almost certainly a manifest mistake).

Validation failures are returned as a list of `(field/path, message)` pairs — never a single
opaque error — so `skillctl validate` and the Web upload flow (T4.2) can render actionable
feedback.

## 5. Versioning policy

- `manifestVersion` is an integer, bumped only for breaking schema/semantic changes.
- Non-breaking additive fields (new optional field, widened enum) do **not** bump
  `manifestVersion` — they get a note in this file's changelog instead.
- The validator and schema are versioned in lockstep: `skill-manifest-v{N}.md` +
  `skill-manifest-v{N}.schema.json`. The validator dispatches on `manifestVersion` and keeps
  old-version schemas around for as long as artifacts of that version may still be installed.

## 6. Changelog

- **v1 (initial)** — fields as above.
