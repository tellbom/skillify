"""Derive displayable governance facts from generated artifact metadata."""

from __future__ import annotations

from typing import Any, Mapping


def derive_artifact_governance(artifact: Mapping[str, Any]) -> dict[str, Any]:
    manifest = artifact.get("skillManifest")
    scan = artifact.get("scan")
    if not isinstance(manifest, dict) or not isinstance(scan, dict):
        raise ValueError("artifact governance requires skillManifest and scan objects")
    findings = scan.get("findings")
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise ValueError("artifact scan findings are invalid")
    levels = {item.get("level") for item in findings}
    scan_status = "blocked" if scan.get("blocked") is True or "block" in levels else (
        "warnings" if "warning" in levels else "passed"
    )
    permissions = manifest.get("permissions") or {}
    if not isinstance(permissions, dict):
        permissions = {}
    labels = [
        name for name, key in (
            ("read", "readPaths"), ("write", "writePaths"), ("command", "commands"),
            ("network", "networkDomains"), ("mcp", "mcpServers"),
            ("database", "databaseResources"),
        ) if permissions.get(key)
    ]
    workflow = artifact.get("workflowDefinition")
    workflow_id = workflow.get("id") if isinstance(workflow, dict) else None
    replay = artifact.get("replayEvaluation")
    return {
        # Executor compatibility is intentionally not inferred from author-declared targets.
        "compatibleExecutors": [],
        "requiredMcp": list(permissions.get("mcpServers") or []),
        "permissions": labels,
        "scanStatus": scan_status,
        "examples": [],
        "workflowId": workflow_id if isinstance(workflow_id, str) else None,
        "replayGate": replay if isinstance(replay, dict) else None,
    }
