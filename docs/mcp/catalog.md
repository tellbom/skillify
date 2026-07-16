# Approved internal MCP connector catalog

This catalog is the development-time source of truth for MCP capabilities distributed by
Skillify. A connector is not production-approved until its `[test-env]` smoke is recorded.
Native local tools remain native; MCP is reserved for reusable evidence or external-system
boundaries.

| Connector | Owner | Version / source | Data class | Default permission | Network | Maintenance | Dev smoke | Test-env smoke |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Code Map query | Skillify endpoint team | Built-in `skillify-codemap` 1.0.0 | Internal source metadata and `path:line` evidence; no source body | Read-only, bounded query types | None; local stdio | In repository | `tests/test_codemap_interfaces.py` | Pending medium-repository evidence jump |
| DM8 metadata/query | Skillify data platform | Planned governed compatibility layer over an approved SQL MCP runtime | Internal business data; configured sensitive columns | Read-only account, SELECT/metadata allowlist, row/byte/time limits | Endpoint/server to internal DM8 only | Skillify adapter; SQL runtime version pinned at approval | Task 6.2 SQLite policy suite | Pending real DM8 dialect/account smoke |
| Forgejo repository | Skillify developer platform | Existing pinned Skillify Forgejo REST client exposed through a bounded MCP adapter | Internal repository metadata, issues, diffs, releases | Read-only by default; each write tool separately granted | Internal Forgejo HTTPS | In repository | Task 6.3 fake Forgejo contract | Pending internal Forgejo token/scope smoke |
| Internal documentation search | Documentation owner + Skillify | Planned adapter; backend selected in test environment | Internal documents and search snippets | Read-only, collection allowlist | Approved internal documentation host only | Owner named at onboarding | Task 6.3 scope contract | Pending backend selection and smoke |
| CI status | Skillify developer platform | Planned Forgejo CI/status adapter | Build status, logs, artifact metadata | Read-only by default; rerun/cancel require explicit grant | Internal Forgejo/runner API only | In repository | Task 6.3 authorization gate | Pending internal CI smoke |

## Evaluated native capabilities

| Capability | Existing interface | Decision |
| --- | --- | --- |
| Local file read/write and process execution | Endpoint Agent/OpenCode native tools plus `PermissionManifest` | Keep native. Wrapping these in MCP would duplicate the local permission boundary. |
| Skill/Workflow/MCP install and lock operations | `skillctl` and capability distribution modules | Keep native CLI/library operations. They mutate endpoint configuration and already have preview/ownership semantics. |
| Endpoint task polling and event reporting | Signed task protocol and outbound HTTP Bridge | Keep as control-plane HTTP, not MCP. It is lifecycle transport rather than a reusable model tool. |
| Forgejo publish/install lifecycle | Existing `skillctl` commands and `ForgejoClient` | Keep mutation workflows in current services; only bounded developer read tools enter the MCP adapter by default. |

## Approval rules

- Every distributed connector uses exact artifact version, checksum, source, license, owner,
  permission summary, and transport metadata from the existing MCP registry contract.
- Credentials are references, never catalog values. Service/admin tokens are not distributed.
- Write tools are absent or disabled unless named individually in a task permission policy.
- A Dev smoke proves schema, scope, and fake behavior only. The last column must be completed in
  the designated environment before claiming real connector availability.
