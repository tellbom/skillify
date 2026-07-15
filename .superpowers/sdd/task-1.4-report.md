# Task 1.4 report — Offline Distribution and Compatibility Lock

## Status

Implemented the pinned OpenCode v1.15.11 offline distribution manifest, strict
manifest validation and artifact verification, manifest-driven doctor checks,
dependency-injected doctor configuration, and the disconnected deployment
runbook. No runtime download path was added.

## TDD evidence

- Distribution RED: `ModuleNotFoundError: No module named
  'skillify.install.opencode_distribution'`.
- Distribution GREEN: `7 passed in 0.16s`.
- Doctor RED: missing `_check_opencode_distribution` and `run_doctor()` rejected
  `agent_paths` (3 failed, 12 passed).
- Doctor GREEN: `15 passed in 2.82s`.
- Review RED: a version timeout escaped the doctor check (`1 failed`), and two
  non-canonical source/bundle URIs were accepted (`2 failed`).
- Review GREEN: doctor reports subprocess failures, and every selector is locked
  to its exact official source filename and absolute local bundle URI
  (`18 passed in 2.81s` for doctor/distribution).

## Verification

- `uv run --no-sync python -m compileall -q src`: exit 0.
- Focused S1 modules after review fixes: `131 passed, 1 skipped in 10.38s`; the skip is the expected
  `requires test-env:` OpenCode provider smoke.
- Full pytest: `442 passed, 2 skipped, 1 failed`; the only failure is the recorded
  baseline `tests/test_projector.py::test_project_uses_symlink_when_forced`.
- `cd web && npm run type-check`: exit 0.
- `cd web && npm test`: 165 passed, one recorded baseline failure in
  `appFooter.spec.js`.
- `cd web && npm run build`: exit 0 with the recorded chunk/dynamic-import warnings.
- `git diff --check`: exit 0.
- Prohibited-pattern review: new-code hits are limited to assertions/rejection
  wording for `latest`; the runbook's direct HTTPS `curl` is staging-only and is
  not piped to a shell. No runtime public downloader, `0.0.0.0`, or embedded
  OpenCode password was added.

## Remaining G1 evidence

The runbook marks real disconnected upgrade/downgrade, exact target platform,
internal model/MCP, localhost listener, cancellation/SIGTERM, and residual-process
checks as `[test-env]`. These require an approved Linux target and were not run
on this macOS development host.

## Formal review corrections

- `verify_artifact()` now converts missing and unreadable paths to
  `ArtifactNotFound`. RED: two native `OSError` failures; GREEN: `2 passed`.
- A shared distribution helper now owns path resolution, platform/version
  probing, and staged manifest/platform/version/checksum diagnostics. RED: seven
  missing-helper failures; GREEN: `7 passed` with stage-specific detail/hints.
- `skillctl agent doctor --format json` now includes distribution checks when
  configured. Success preserves exit 0/`OK`; distribution failure preserves exit
  12/`AGENT_PROVIDER_UNAVAILABLE`, the four-key envelope, and exposes diagnostic
  data. RED: missing distribution data and corrupt artifact incorrectly exited
  0; GREEN: `2 passed`.
- The runbook now explicitly installs the manifest at the configured parent path
  and the selected artifact in the v1.15.11 directory. RED: missing command
  assertion; GREEN: `1 passed`.
- Post-correction compileall exited 0 and focused S1 regression reported
  `143 passed, 1 skipped in 10.48s`.
