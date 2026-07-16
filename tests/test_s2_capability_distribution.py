"""G2 offline acceptance for governed capability distribution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from skillify.agent.capability_lock import (
    CapabilityKind,
    CapabilityLockStore,
    LockedDependency,
)
from skillify.agent.opencode_config import (
    CapabilitySource,
    MutationKind,
    OpenCodeScopePaths,
    apply_install,
    apply_uninstall,
    plan_install,
    plan_uninstall,
    rollback_install,
)
from skillify.agent.permissions import PermissionManifest, merge_permissions
from skillify.install.resolver import Coordinate, ReleaseRecord, resolve_capability_graph
from skillify.mcp.registry import (
    McpRegistry,
    load_mcp_artifact,
    mcp_artifact_as_dict,
)


FIXED_TIME = "2026-07-16T00:00:00+00:00"
FORGEJO = "https://forgejo.internal"


class FakeReleaseCatalog:
    def __init__(self, records: tuple[ReleaseRecord, ...]) -> None:
        self.records = {record.coordinate: record for record in records}
        self.calls = 0

    def get(self, coordinate: Coordinate) -> ReleaseRecord | None:
        self.calls += 1
        return self.records.get(coordinate)


def _permissions() -> dict[str, object]:
    return {
        "readPaths": ["docs/**"],
        "writePaths": [],
        "commands": {},
        "networkDomains": [],
        "mcpServers": ["approved.echo"],
        "databaseResources": [],
        "unattended": False,
        "confirm": [],
    }


def _echo_artifact():
    value = {
        "schemaVersion": 1,
        "artifactKind": "mcp",
        "namespace": "approved",
        "name": "echo",
        "version": "1.2.3",
        "forgejoRelease": "v1.2.3",
        "commit": "b" * 40,
        "checksum": "e" * 64,
        "license": "MIT",
        "source": (
            f"{FORGEJO}/approved/echo/releases/download/"
            "v1.2.3/approved-echo-1.2.3.tar.gz"
        ),
        "transport": "stdio",
        "command": ["/opt/skillify/mcp/echo/bin/server", "--stdio"],
        "environment": [],
        "permissions": _permissions(),
        "enabled": True,
    }
    return load_mcp_artifact(value, approved_forgejo_base=FORGEJO)


def _skill_source(
    tmp_path: Path, *, version: str, command_body: str, include_stale: bool
) -> CapabilitySource:
    root = tmp_path / f"reviewer-{version}"
    for directory in ("agents", "commands", "plugins", "mcp"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "---\nname: reviewer\ndescription: governed reviewer\n---\nreview\n",
        encoding="utf-8",
    )
    (root / "agents/reviewer.md").write_text("review agent", encoding="utf-8")
    (root / "commands/review.md").write_text(command_body, encoding="utf-8")
    (root / "plugins/governed-tools.js").write_text(
        "export default {}", encoding="utf-8"
    )
    (root / "mcp/echo.yaml").write_text(
        yaml.safe_dump(mcp_artifact_as_dict(_echo_artifact())), encoding="utf-8"
    )
    commands = {"review": "commands/review.md"}
    if include_stale:
        (root / "commands/legacy.md").write_text("legacy", encoding="utf-8")
        commands["legacy"] = "commands/legacy.md"
    manifest = {
        "manifestVersion": 1,
        "namespace": "approved",
        "name": "reviewer",
        "version": version,
        "description": "governed reviewer",
        "author": "Skillify",
        "license": "MIT",
        "runtime": "custom",
        "targets": ["opencode"],
        "entrypoints": {
            "agents": {"reviewer": "agents/reviewer.md"},
            "commands": commands,
            "plugins": {"governed-tools": "plugins/governed-tools.js"},
            "mcp": {"echo": "mcp/echo.yaml"},
        },
        "permissions": {"readPaths": ["docs/**"], "mcpServers": ["approved.echo"]},
    }
    (root / "skill.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    checksum = hashlib.sha256((root / "skill.yaml").read_bytes()).hexdigest()
    return CapabilitySource(
        root=root,
        coordinate=Coordinate("skill", "approved/reviewer", version),
        forgejo_release=f"v{version}",
        commit="a" * 40,
        checksum=checksum,
        dependencies=(
            LockedDependency("mcp", "approved/echo", "1.2.3", "e" * 64),
        ),
        permissions=merge_permissions(
            (PermissionManifest.from_value("approved.reviewer", manifest["permissions"]),)
        ),
    )


def test_g2_workflow_pack_installs_updates_rolls_back_and_uninstalls_offline(
    tmp_path: Path,
) -> None:
    v1 = _skill_source(tmp_path, version="1.0.0", command_body="review-v1", include_stale=True)
    v2 = _skill_source(tmp_path, version="2.0.0", command_body="review-v2", include_stale=False)
    workflow = ReleaseRecord(
        Coordinate("workflow", "approved/review-pack", "1.0.0"),
        "v1.0.0", "c" * 40, "d" * 64,
        (v1.coordinate, Coordinate("mcp", "approved/echo", "1.2.3")),
    )
    skill_release = ReleaseRecord(
        v1.coordinate, v1.forgejo_release, v1.commit, v1.checksum,
        (Coordinate("mcp", "approved/echo", "1.2.3"),),
    )
    mcp_release = ReleaseRecord(
        Coordinate("mcp", "approved/echo", "1.2.3"),
        "v1.2.3", "b" * 40, "e" * 64, (),
    )
    catalog = FakeReleaseCatalog((workflow, skill_release, mcp_release))
    resolved = resolve_capability_graph(workflow.coordinate, catalog)
    assert [item.coordinate.kind for item in resolved] == [
        CapabilityKind.MCP, CapabilityKind.SKILL, CapabilityKind.WORKFLOW,
    ]

    registry = McpRegistry()
    echo = _echo_artifact()
    registry.register(echo)
    preview = registry.preview(echo).as_dict()
    assert preview["source"].startswith(FORGEJO)
    assert preview["command"] == ["/opt/skillify/mcp/echo/bin/server", "--stdio"]
    assert preview["environmentConstraint"]

    paths = OpenCodeScopePaths.project(tmp_path / "repo", cache_root=tmp_path / "cache")
    store = CapabilityLockStore(tmp_path / "locks")
    paths.commands.mkdir(parents=True)
    (paths.commands / "mine.md").write_text("user-owned", encoding="utf-8")
    paths.config_file.write_text(
        json.dumps({"theme": "dark", "mcp": {"mine": {"type": "remote"}}}),
        encoding="utf-8",
    )

    first_plan = plan_install(
        v1, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    assert first_plan.permission_summary["policies"][0]["mcpServers"] == ["approved.echo"]
    first = apply_install(first_plan)
    repeated = plan_install(
        v1, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    assert {item.kind for item in repeated.mutations} == {MutationKind.UNCHANGED}
    assert apply_install(repeated).changed is False

    second = apply_install(plan_install(
        v2, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    assert second.lock.version == "2.0.0"
    assert not (paths.commands / "legacy.md").exists()
    assert (paths.commands / "mine.md").read_text(encoding="utf-8") == "user-owned"
    config = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert config["theme"] == "dark"
    assert config["mcp"]["mine"] == {"type": "remote"}
    assert config["mcp"]["echo"]["type"] == "local"

    calls_before_rollback = catalog.calls
    rolled = rollback_install(first.lock.digest, paths=paths, lock_store=store)
    assert rolled.lock.version == "1.0.0"
    assert catalog.calls == calls_before_rollback
    assert (paths.commands / "review.md").read_text(encoding="utf-8") == "review-v1"

    apply_uninstall(plan_uninstall(rolled.lock, paths=paths, lock_store=store))
    assert not (paths.commands / "review.md").exists()
    assert (paths.commands / "mine.md").read_text(encoding="utf-8") == "user-owned"
    final_config = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert final_config == {"mcp": {"mine": {"type": "remote"}}, "theme": "dark"}

    empty_paths = OpenCodeScopePaths.project(
        tmp_path / "empty-repo", cache_root=tmp_path / "empty-cache"
    )
    empty_store = CapabilityLockStore(tmp_path / "empty-locks")
    empty_paths.config_file.parent.mkdir(parents=True)
    empty_paths.config_file.write_text("{}\n", encoding="utf-8")
    empty_install = apply_install(plan_install(
        v1, paths=empty_paths, lock_store=empty_store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    apply_uninstall(plan_uninstall(
        empty_install.lock, paths=empty_paths, lock_store=empty_store
    ))
    assert empty_paths.config_file.is_file()
    assert json.loads(empty_paths.config_file.read_text(encoding="utf-8")) == {}
