# Capability distribution operations

Skillify installs an immutable capability source into an explicitly injected
OpenCode user or project scope. The adapter keeps the two scopes in separate
targets, ownership locks, and rollback snapshots. Real OpenCode precedence when
both scopes contain the same name remains a `[test-env]` check.

## Operator flow

1. Resolve the Workflow/Skill/MCP graph from exact semantic versions and
   immutable Forgejo releases, then verify each downloaded checksum.
2. Build an install plan with `plan_install()`. Review its ordered mutations,
   merged permission summary, and each MCP preview. A local MCP preview exposes
   the exact governed binary argv, approved source, checksum, closed argument
   rules, and referenced `SKILLIFY_MCP_*` credential names without secret values.
3. Use `apply_install(plan, dry_run=True)` for a write-free preview. Apply the
   same plan without `dry_run` only after approval. Apply rechecks the current
   ownership lock and every target checksum under the local transaction lock.
4. Update by planning the new exact release. Stale generated files or MCP keys
   are removed only when their bytes still match the prior ownership record.
5. Roll back with `rollback_install(<lock-digest>, ...)`. Rollback reads the
   checksum-verified private snapshot and stored lock; it performs no catalog,
   resolver, Forgejo, devpi, or public-network request.
6. Uninstall with `plan_uninstall()` followed by `apply_uninstall()`. Only files
   and `/mcp/<name>` entries recorded in the exact current lock are removed.

Unowned destinations, changed owned content, stale plans, symlinked paths, and
invalid `opencode.json` content are conflicts. Skillify never silently replaces
them. Unrelated files and JSON sibling keys are retained throughout install,
update, rollback, and uninstall.

Locks and content-addressed history live in the injected `CapabilityLockStore`.
Rollback snapshots and the adapter transaction lock live below the injected
Skillify agent cache. These directories are private (`0700`) and their files are
private (`0600`). Handled apply failures restore the captured target bytes and
prior lock. Crash/power-loss recovery is deliberately deferred to the planned
system-level hardening pass. Permission audit records use the Task 2.3
redaction rules; the caller supplies the local file path to
`write_authorization_audit()` (mode `0600`). They are never written into
OpenCode configuration.

## Environment-only acceptance

The offline G2 fixture verifies deterministic resolution, preview, project-scope
install, idempotency, update, exact rollback, uninstall, local MCP rendering,
and preservation of user-owned configuration. The following remain
`[test-env]` because they require approved infrastructure or a real endpoint:

- real OpenCode loading the generated skill, agent, command, plugin, and MCP;
- checksum verification against a real Forgejo release asset;
- approved internal remote MCP HTTPS smoke testing;
- real endpoint permission-confirmation interaction;
- the combined Linux/OpenCode/Forgejo/internal-MCP G2 run.
