"""T6.2 — opt-in client->server event reporting.

Privacy boundary (documented per TASKS.md T6.2 acceptance):
  - **Off by default.** Nothing is sent anywhere unless both `web_base_url` is configured
    AND `reporting_enabled: true` is set (~/.skillify/config.yaml or
    SKILLIFY_REPORTING_ENABLED=1) — mirrors the `reporting.enabled` opt-in field already
    reserved in every skill's own `skill.yaml` (spec/skill-manifest-v1.md §3).
  - **What's collected**: skill namespace/name/version, event type ("install"/"run"),
    success (run events only), and an opaque per-machine id (a random UUID generated once
    and cached at `~/.skillify/machine_id` — not a hardware/MAC-derived fingerprint).
  - **What's never collected**: usernames, IP addresses (beyond whatever the HTTP transport
    layer inherently sees), skill inputs/outputs/arguments, file paths, or any other
    environment detail. The server side (`skillify/index/models.py:SkillEvent`) has no
    columns for any of that — the schema itself is the enforcement mechanism.
  - Reporting failures are always best-effort and silent (never raise, never block the
    caller) — same posture as T2.2's index write and T1.x's Forgejo/devpi network calls
    that are allowed to be unreachable in an intranet deployment.
"""

from __future__ import annotations

import uuid

import requests

from skillify.common.config import SkillifyConfig


def get_or_create_machine_id(cfg: SkillifyConfig) -> str:
    """A random, non-identifying id — stable across calls on the same machine, but not
    derived from any hardware/network identifier."""
    path = cfg.home / "machine_id"
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    cfg.ensure_dirs()
    machine_id = uuid.uuid4().hex
    path.write_text(machine_id, encoding="utf-8")
    return machine_id


def report_skill_event(
    cfg: SkillifyConfig,
    *,
    namespace: str,
    name: str,
    version: str,
    event_type: str,
    success: bool | None = None,
) -> bool:
    """Best-effort report to `skillify-web`'s `/api/skills/{ns}/{name}/events` (T5.2/T6.2).
    Returns True if the report was sent successfully, False otherwise — never raises."""
    if not cfg.reporting_enabled or not cfg.web_base_url:
        return False
    try:
        machine_id = get_or_create_machine_id(cfg)
        resp = requests.post(
            f"{cfg.web_base_url.rstrip('/')}/api/skills/{namespace}/{name}/events",
            json={"eventType": event_type, "version": version, "success": success, "machineId": machine_id},
            timeout=3,
        )
        return resp.status_code == 204
    except requests.RequestException:
        return False
