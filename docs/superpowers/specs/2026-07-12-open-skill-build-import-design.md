# Open Skill Build and Import Design

## Goal

Add backend APIs that let technical and non-technical users create, convert, preview,
confirm, and publish Skills without requiring a ready-made Skillify zip or a handwritten
complete `skill.yaml`. The existing standard zip upload, guided creation, and external
Agent Skill import have different source adapters but converge on one Skillify Native
workspace and one formal publish service.

No web UI is included. The API contract will be documented in `README.md` for a separate
frontend implementation.

## Scope

This change includes:

- changing the existing standard zip upload from immediate publication to preview creation;
- guided creation from manifest fields, `SKILL.md`, and optional uploaded files;
- scanning external Agent Skill zip archives, including archives with multiple `SKILL.md`
  candidates;
- explicit selection of one or more external candidates;
- explicit completion and confirmation of Skillify manifest fields;
- complete Native manifest, directory tree, detected facts, and validation previews;
- revision-protected final confirmation;
- one shared formal publication path;
- API tests and README API documentation.

This change does not include:

- frontend code;
- a persistent or user-visible draft box;
- restoring temporary builds after a backend restart;
- Git URL import;
- inference of missing metadata from filenames, scripts, repository names, or source code;
- a new manifest schema or fields that duplicate `skill.yaml` v1.

## Design Principles

1. `skill.yaml` manifest v1 remains the only canonical metadata model.
2. Source adapters may differ, but validation, preview, confirmation, namespace ownership,
   packaging, Forgejo release creation, checksum generation, indexing, and publish-job
   recording are shared.
3. The backend publishes exactly the revision that the user previewed.
4. External import reports facts and missing data; it does not guess.
5. Temporary server-side staging exists only to support preview and confirmation. It is not
   exposed as a draft list and expires after 24 hours by default.

## Approaches Considered

### Selected: source adapters plus canonical staged workspace

Each entry adapter produces a canonical Skillify Native workspace. The backend stores it
temporarily and returns an opaque build ID plus a monotonically increasing revision. All
edits regenerate the preview. Final publication accepts only the current revision.

This provides one data model, avoids retransmitting all files at confirmation time, and
proves that the published bytes match the preview.

### Rejected: stateless client round-trip

The client could send all manifest data and files again during publication. This avoids
temporary storage but duplicates large uploads and cannot reliably prove the published
content is the content previously previewed.

### Rejected: independent entry workflows sharing only the publisher

Separate validation and conversion logic for each entry would be quicker initially, but it
would allow field mappings, security checks, and Native structures to diverge.

## Architecture

```text
standard Skillify zip ---------> native zip adapter ----┐
guided fields/content/files ---> guided adapter ---------+--> NativeBuild workspace
external Agent Skill zip ------> scan/select adapter ----┘          |
                                                                    +--> preview
                                                                    +--> validation
                                                                    +--> revision
                                                                          |
                                                               explicit confirmation
                                                                          |
                                                               formal publish service
                                                                          |
                                        ownership -> validate -> Git/Release -> index/job
```

The new implementation is split into focused units:

- staging store: owns build IDs, user isolation, expiry, revision checks, and workspace files;
- preview builder: serializes the exact manifest, directory tree, detected facts, readiness,
  and validation issues;
- native zip adapter: safely extracts an existing Skillify archive into a build;
- guided adapter: converts form fields and `SKILL.md` text into a build;
- external scanner: finds `SKILL.md` candidates and records only observable facts;
- external converter: copies selected candidate trees and applies user-confirmed manifest
  values;
- publish service: publishes a validated staged workspace through the existing packaging,
  Forgejo, index, ownership, and publish-job behavior.

## Temporary Staging

Builds are stored beneath the configured Skillify cache directory. Each build contains:

- an opaque UUID build ID;
- the authenticated owner's username;
- source type: `native_zip`, `guided`, or `external`;
- creation and expiry timestamps;
- integer revision starting at `1`;
- status: `needs_input`, `ready`, `publishing`, or `published`;
- canonical workspace files;
- detected facts and externally confirmed field names.

External scans are separate temporary objects because one archive can produce multiple
builds. A scan contains the safely extracted archive and its candidate list. Selecting
multiple candidates creates one independent build per candidate, so each Skill can be
completed, previewed, and published independently.

Temporary objects expire after `SKILLIFY_BUILD_TTL_SECONDS`, default `86400`. Expired or
unknown IDs return `404`. IDs owned by another authenticated user also return `404` to avoid
leaking their existence. Expired data is removed opportunistically during build and scan
operations. No list endpoint is provided.

## Canonical Preview Model

All three entry paths return the same build preview shape:

```json
{
  "buildId": "opaque UUID",
  "sourceType": "guided",
  "revision": 1,
  "status": "needs_input",
  "expiresAt": "2026-07-13T10:00:00Z",
  "manifest": {},
  "manifestYaml": "",
  "skillMd": "---\nname: example\n...",
  "tree": [{"path": "SKILL.md", "type": "file", "size": 120}],
  "detectedFacts": {},
  "missingFields": ["namespace", "version"],
  "unconfirmedFields": [],
  "issues": [{"path": "skill.yaml:namespace", "message": "required"}],
  "publishable": false
}
```

`manifest` and `manifestYaml` are two representations of the same v1 manifest. They are
never separate inputs. `manifestYaml` is generated by the backend for exact preview.
`tree` contains normalized relative POSIX paths and file sizes, sorted by path.

`publishable` is true only when:

- all required manifest values are present;
- external-import confirmation requirements are satisfied;
- the canonical Skill directory passes the existing validator.

## Entry 1: Standard Skillify Zip

`POST /api/skills/upload` remains the standard upload path but no longer publishes. It
accepts a `.zip`, applies the existing raw-size, decompressed-size, file-count, symlink, and
path-traversal protections, requires one resolvable root with `skill.yaml` and `SKILL.md`,
and creates a Native build preview.

Values already present in a valid uploaded `skill.yaml` are source-provided facts and do not
need field-by-field reconfirmation. The user still must inspect the complete preview and call
the final confirmation endpoint.

## Entry 2: Guided Creation

`POST /api/skill-builds/guided` accepts JSON containing:

- `manifest`: a partial or complete manifest v1 object;
- `skillMd`: current `SKILL.md` text.

The endpoint supports incomplete requests so the frontend can refresh the preview while the
user progresses through its steps. It never introduces alternate names for manifest fields.
For example, the UI's type selection writes the existing `runtime` field, and the basic
information step writes `namespace`, `name`, `version`, `description`, `author`, `license`,
`targets`, and `tags` directly.

`PATCH /api/skill-builds/{build_id}` replaces provided manifest fields or `skillMd`, checks
`expectedRevision`, increments the revision, regenerates `skill.yaml`, and returns the full
preview.

Optional scripts and resources use:

- `POST /api/skill-builds/{build_id}/files` with multipart `path`, `file`, and
  `expectedRevision`;
- `DELETE /api/skill-builds/{build_id}/files?path=...&expectedRevision=...`.

Uploaded paths must be safe relative paths. `skill.yaml` and `SKILL.md` are reserved and can
only be changed through the structured build update. File count and total staged size remain
within the existing configured extraction limits.

## Entry 3: External Agent Skill Import

`POST /api/external-skill-scans` accepts a `.zip`, safely extracts it, recursively finds every
file named exactly `SKILL.md`, and returns:

```json
{
  "scanId": "opaque UUID",
  "expiresAt": "2026-07-13T10:00:00Z",
  "candidates": [
    {
      "candidateId": "stable opaque ID",
      "rootPath": "skills/example",
      "frontmatter": {"name": "example", "description": "..."},
      "detectedPaths": ["scripts", "assets", "requirements.txt"],
      "issues": []
    }
  ]
}
```

An archive without `SKILL.md` returns `422`. Malformed frontmatter is reported on that
candidate and is not replaced with inferred data. Multiple candidates are not treated as an
error.

`POST /api/external-skill-scans/{scan_id}/selections` accepts one or more candidate IDs and
creates one external Native build per selected candidate. Candidate IDs must belong to that
scan and duplicate selections are rejected.

### No-guess conversion policy

The scanner may report only facts directly supported by files:

- `name` and `description` exactly as declared in valid `SKILL.md` frontmatter;
- Python requirements exactly declared by `requirements.txt`;
- Python project dependencies explicitly declared in supported `pyproject.toml` project
  metadata;
- presence of `scripts`, `assets`, `references`, `resources`, `examples`,
  `requirements.txt`, `pyproject.toml`, and `package.json`.

It must not:

- derive a namespace or name from archive, repository, or directory names;
- normalize an invalid name into a valid slug;
- invent version, author, license, runtime, or targets;
- infer permissions by reading scripts;
- infer tags from prose or paths;
- map `package.json` packages into Python, system, or Skill dependencies;
- infer dependencies that are not explicitly declared.

External builds distinguish three concepts:

- `detectedFacts`: evidence extracted from the external files;
- `missingFields`: fields with no source or user value;
- `unconfirmedFields`: fields that have a detected value but still require explicit user
  confirmation.

Before an external build can become publishable, the user must submit or explicitly confirm
`namespace`, `name`, `version`, `description`, `author`, `license`, `runtime`, `targets`,
`dependencies`, `permissions`, and `tags`. Sending the complete values through the build
update endpoint constitutes confirmation. Empty optional collections are accepted only when
the user explicitly sends them.

The backend may add only manifest v1's deterministic structural defaults:
`manifestVersion: 1`, `entrypoints: {}`, `orchestration: {}`, and
`reporting: {enabled: false}`. These are schema defaults, not metadata guesses.

## Unified Publication

`POST /api/skill-builds/{build_id}/publish` accepts:

```json
{"expectedRevision": 4, "confirmed": true}
```

The endpoint performs these checks in order:

1. authenticate and load the caller-owned, unexpired build;
2. reject `confirmed != true`;
3. compare `expectedRevision` with the current revision;
4. require `publishable == true` and rerun full directory validation;
5. atomically mark the build `publishing` to reject duplicate confirmation requests;
6. call the single formal publish service;
7. return the existing publication result shape plus `buildId` and published revision;
8. mark the build `published` and keep it only until normal expiry for idempotent status
   reporting.

The formal publish service reuses the current behavior for declared-name rehoming,
namespace ownership, optional Git source push, packaging, checksum generation, Forgejo
Release, index ingestion, and publish-job recording. The former immediate-upload handler is
refactored so neither standard zip nor another adapter can bypass this service.

## API Errors

Errors use FastAPI's existing `detail` convention:

- `400`: invalid extension, unsafe path, malformed request, or invalid candidate selection;
- `401`: missing or invalid Keycloak token;
- `404`: unknown, expired, or other-user scan/build;
- `409`: stale revision, build already publishing/published, or already-published version;
- `413`: raw upload or staged content exceeds configured limits;
- `422`: no external candidates, invalid Native structure, missing confirmation, or validation
  issues; structured validation issues retain `{path, message}` entries;
- `503`: index or publication configuration missing;
- `502`: Forgejo failure.

Revision conflicts return the current revision so the frontend can refresh the preview.
Readiness failures return `missingFields`, `unconfirmedFields`, and validation `issues`.

## Security

- All APIs require the existing Keycloak bearer authentication.
- Every temporary object is owner-bound and addressed by an unguessable UUID.
- Zip safety and configured byte/file caps are shared with the existing upload path.
- File mutation rejects absolute paths, `..`, drive prefixes, backslash traversal, symlinks,
  and reserved manifest paths.
- Candidate roots never escape the extracted scan directory.
- Frontmatter and dependency parsing do not execute external code.
- Final publication reruns validation and namespace authorization; preview never reserves a
  namespace.

## Testing Strategy

Tests follow red-green-refactor and cover:

- standard upload creates a preview and does not create a Forgejo Release before confirmation;
- guided partial input reports missing fields and becomes publishable after valid completion;
- file add/delete updates the tree and revision and blocks unsafe/reserved paths;
- external scans find zero, one, and multiple candidates;
- external scans report explicit facts while never deriving absent values;
- selection of multiple candidates creates independent builds;
- external builds require explicit confirmation of all conversion fields, including empty
  optional collections;
- stale revisions, expired builds, cross-user access, and duplicate publish requests fail;
- every source type reaches the same formal publish service;
- final confirmation publishes the exact previewed manifest and file tree;
- the existing upload bomb, path traversal, ownership, duplicate version, Forgejo, indexing,
  and publish-job behaviors remain covered after endpoint semantics change;
- OpenAPI response schemas and README examples agree with implemented fields.

## Compatibility and Documentation

`POST /api/skills/upload` intentionally changes from immediate publication to preview
creation. The old `UploadResponse` is replaced by the canonical build preview. Frontend code
must call the unified publish endpoint after rendering the preview and receiving explicit
confirmation.

`README.md` will document authentication, endpoint order, request and response examples,
external multi-Skill selection, no-guess behavior, revisions, expiration, error handling,
and the intentional compatibility change. Git import will be described only as deferred and
will not appear as a working endpoint.
