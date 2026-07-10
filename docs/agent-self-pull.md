# Agent self-pull channel (T6.1)

> Status: 预留接口 (reserved interface) per TASKS.md M6 — this documents the intended
> protocol and its current security posture, not a fully hardened production path. See
> "Known gaps" at the bottom before relying on this for anything beyond an intranet MVP.

## What this is

PLAN.md §4 describes a "skillsmp 模式" self-pull flow: each skill's detail page exposes a
copy-pasteable prompt (`GET /api/skills/{namespace}/{name}/install`'s `agentPrompt` field,
also embedded in the skill detail response) that an agent (e.g. Claude Code) can follow to
install a skill on its own, without a human running `skillctl` for it.

## The two paths

1. **Preferred — `skillctl install <namespace>/<name>`.** If `skillctl` is available and
   configured (Forgejo URL/token), this is the same download→verify→extract→lock pipeline
   used by every other install path in this project (T1.4/T1.4a/T1.5). Nothing new here.

2. **Fallback — self-contained fetch/verify/extract**, for an agent that doesn't have
   `skillctl` on its PATH. The recipe (see `agent_prompt()` in `skillify/web/service.py`):
   1. `GET {SKILLIFY_WEB_BASE_URL}/api/skills/{namespace}/{name}` — the same detail endpoint
      T3.1 already serves for the web UI. Read `tarballUrl` and `checksumUrl`.
   2. Download both.
   3. Compute the tarball's sha256 and compare against the checksum file's contents —
      **do not extract or execute anything before this check passes.** This mirrors
      `install/extract.verify_checksum`'s guarantee, just re-implemented by hand since the
      agent isn't calling into skillify's own Python code.
   4. Extract the tarball into the target agent's skills directory (e.g.
      `~/.claude/skills/{namespace}__{name}/` for Claude Code, matching the naming
      convention `skillify/install/agent_defaults.py` already uses for `skillctl`-driven
      installs — see T1.4a).

   `tarballUrl`/`checksumUrl` are resolved server-side using the exact same basename-precise
   matching C2 added to `skillify/install/resolver.py` (`<namespace>-<name>-<version>.*`), so
   an agent following this recipe gets the identical artifact `skillctl install` would have
   fetched — not a looser "first tarball on the release" match.

## Security posture

PLAN.md §4/§6.4 calls for this channel to be "限内网 + token 认证" (intranet-only + token
auth). As implemented:

- **Intranet-only**: enforced operationally (the service isn't exposed outside the intranet),
  not by application-layer IP allowlisting in this codebase.
- **Token auth (updated by M-A, docs/review-m2-m6.md)**: `GET /api/skills/{namespace}/{name}`
  is no longer anonymous — the market-wide login decision (M-A) put every read endpoint
  behind `require_keycloak_user`, this one included. So an agent following this recipe now
  needs a Keycloak bearer token to complete step 1, same as browsing the web UI. Per the
  joint review's M-H item, this was a **decision explicitly deferred** (2026, docs/review-
  m2-m6.md): no *dedicated* self-pull token/key mechanism (distinct from the Keycloak
  session) has been built, and none is planned until a real agent depends on this channel —
  it continues to inherit whatever auth the underlying detail endpoint happens to require,
  rather than having its own independent access boundary. The actual artifact download
  (`tarballUrl`/`checksumUrl`) still comes from Forgejo's `browser_download_url`, gated by
  whatever visibility Forgejo itself has configured on that repo.
- Supply-chain integrity (the part that *is* fully implemented): checksum verification is
  mandatory in the recipe, and the detail endpoint's URLs are resolved with the same
  C2-precise asset matching used everywhere else, so a compromised/mislabeled Release asset
  can't silently substitute a different tarball for the one requested.

## Known gaps

- No Skillify-issued API token/key mechanism exists yet for this channel specifically —
  it rides on the same Keycloak bearer auth as the rest of the API (M-A) rather than having
  an independently scoped credential. If a future deployment needs to restrict *which*
  agents/machines can self-pull (as opposed to which humans can browse), that requires
  adding a token layer here — tracked as follow-up, not implemented in this pass (T6.1/M-H
  are explicitly framed as reserved/stub, not a hardening pass; re-evaluate once a real
  agent actually depends on this channel).
- No MCP server implementation — PLAN.md §2 lists "文档化拉取端点 / MCP（预留）" as
  alternatives; this pass implements the documented-endpoint half only.
