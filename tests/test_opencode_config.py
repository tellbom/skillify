from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml

from skillify.agent.capability_lock import CapabilityKind, CapabilityLockStore, InstallScope
from skillify.agent.opencode_config import (
    CapabilitySource,
    MutationKind,
    OpenCodeConfigError,
    OpenCodeConfigConflict,
    OpenCodeScopePaths,
    apply_install,
    apply_uninstall,
    plan_install,
    plan_uninstall,
    rollback_install,
)
from skillify.agent.permissions import PermissionManifest, merge_permissions
from skillify.install.resolver import Coordinate
from skillify.mcp.registry import McpRegistry, load_mcp_artifact, mcp_artifact_as_dict


FIXED_TIME = "2026-07-16T00:00:00+00:00"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _bundle(tmp_path: Path, *, version: str = "1.0.0", command: str = "review-v1", stale: bool = True) -> CapabilitySource:
    root = tmp_path / f"bundle-{version}"
    (root / "agents").mkdir(parents=True)
    (root / "commands").mkdir()
    (root / "plugins").mkdir()
    (root / "SKILL.md").write_text("---\nname: reviewer\ndescription: x\n---\nbody\n", encoding="utf-8")
    (root / "agents/reviewer.md").write_text("agent", encoding="utf-8")
    (root / "commands/review.md").write_text(command, encoding="utf-8")
    (root / "plugins/governed-tools.js").write_text("export default {}", encoding="utf-8")
    entrypoints = {
        "agents": {"reviewer": "agents/reviewer.md"},
        "commands": {"review": "commands/review.md"},
        "plugins": {"governed-tools": "plugins/governed-tools.js"},
    }
    if stale:
        (root / "commands/stale.md").write_text("stale", encoding="utf-8")
        entrypoints["commands"]["stale"] = "commands/stale.md"
    manifest = {
        "manifestVersion": 1,
        "namespace": "approved",
        "name": "reviewer",
        "version": version,
        "description": "review",
        "author": "Team",
        "license": "MIT",
        "runtime": "custom",
        "targets": ["opencode"],
        "entrypoints": entrypoints,
        "permissions": {"readPaths": ["docs/**"]},
    }
    (root / "skill.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return CapabilitySource(
        root=root,
        coordinate=Coordinate(CapabilityKind.SKILL, "approved/reviewer", version),
        forgejo_release=f"v{version}",
        commit="a" * 40,
        checksum=_sha((root / "skill.yaml").read_bytes()),
        dependencies=(),
        permissions=merge_permissions((PermissionManifest.from_value("approved.reviewer", manifest["permissions"]),)),
    )


def _roots(tmp_path: Path) -> tuple[OpenCodeScopePaths, CapabilityLockStore, McpRegistry]:
    paths = OpenCodeScopePaths.project(tmp_path / "repo", cache_root=tmp_path / "cache")
    return paths, CapabilityLockStore(tmp_path / "locks"), McpRegistry()


def _register_echo_entrypoint(source: CapabilitySource, registry: McpRegistry) -> None:
    artifact = load_mcp_artifact({
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
            "https://forgejo.internal/approved/echo/releases/download/"
            "v1.2.3/approved-echo-1.2.3.tar.gz"
        ),
        "transport": "stdio",
        "command": ["/opt/skillify/mcp/echo/bin/server", "--stdio"],
        "environment": [],
        "permissions": {},
        "enabled": True,
    }, approved_forgejo_base="https://forgejo.internal")
    registry.register(artifact)
    root = Path(source.root)
    (root / "mcp").mkdir()
    (root / "mcp/echo.yaml").write_text(
        yaml.safe_dump(mcp_artifact_as_dict(artifact)), encoding="utf-8"
    )
    manifest = yaml.safe_load((root / "skill.yaml").read_text(encoding="utf-8"))
    manifest["entrypoints"]["mcp"] = {"echo": "mcp/echo.yaml"}
    (root / "skill.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def test_scope_paths_follow_opencode_user_and_project_layout(tmp_path: Path) -> None:
    user = OpenCodeScopePaths.user(tmp_path / "xdg-config" / "opencode")
    project = OpenCodeScopePaths.project(tmp_path / "repo")
    assert user.skills == tmp_path / "xdg-config/opencode/skills"
    assert project.skills == tmp_path / "repo/.opencode/skills"
    assert user.scope is InstallScope.USER
    assert project.scope is InstallScope.PROJECT


def test_planner_is_deterministic_and_dry_run_does_not_write(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    plan = plan_install(source, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME)
    assert plan.mutations == tuple(sorted(plan.mutations, key=lambda item: item.ownership_key))
    assert plan.permission_summary["policies"][0]["readPaths"] == ["docs/**"]
    result = apply_install(plan, dry_run=True)
    assert result.changed is False
    assert not (paths.root / ".opencode").exists()


def test_install_is_idempotent_and_never_overwrites_unowned_file(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    first = apply_install(plan_install(source, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME))
    repeated = plan_install(source, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME)
    assert first.changed is True
    assert {item.kind for item in repeated.mutations} == {MutationKind.UNCHANGED}
    assert apply_install(repeated).changed is False

    other_paths = OpenCodeScopePaths.project(tmp_path / "other", cache_root=tmp_path / "other-cache")
    destination = other_paths.commands / "review.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("user-owned", encoding="utf-8")
    with pytest.raises(OpenCodeConfigConflict, match="not owned"):
        plan_install(source, paths=other_paths, lock_store=CapabilityLockStore(tmp_path / "other-locks"), mcp_registry=registry, installed_at=FIXED_TIME)
    assert destination.read_text(encoding="utf-8") == "user-owned"


def test_update_removes_only_stale_owned_and_preserves_user_siblings(tmp_path: Path) -> None:
    v1 = _bundle(tmp_path, version="1.0.0", stale=True)
    v2 = _bundle(tmp_path, version="2.0.0", command="review-v2", stale=False)
    paths, store, registry = _roots(tmp_path)
    first = apply_install(plan_install(v1, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME))
    sibling = paths.commands / "mine.md"
    sibling.write_text("keep", encoding="utf-8")
    second = apply_install(plan_install(v2, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME))
    assert second.lock.version == "2.0.0"
    assert store.read_digest(first.lock.digest) == first.lock
    assert not (paths.commands / "stale.md").exists()
    assert sibling.read_text(encoding="utf-8") == "keep"


def test_modified_owned_file_blocks_update_and_uninstall(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    update = _bundle(tmp_path, version="1.0.1")
    paths, store, registry = _roots(tmp_path)
    installed = apply_install(plan_install(source, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME))
    target = paths.commands / "review.md"
    target.write_text("user-edit", encoding="utf-8")
    with pytest.raises(OpenCodeConfigConflict, match="modified"):
        plan_install(update, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME)
    with pytest.raises(OpenCodeConfigConflict, match="modified"):
        plan_uninstall(installed.lock, paths=paths, lock_store=store)
    assert target.read_text(encoding="utf-8") == "user-edit"


def test_rollback_uses_verified_snapshot_and_uninstall_preserves_json_siblings(tmp_path: Path) -> None:
    v1 = _bundle(tmp_path, version="1.0.0", command="v1")
    v2 = _bundle(tmp_path, version="2.0.0", command="v2", stale=False)
    paths, store, registry = _roots(tmp_path)
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    first = apply_install(plan_install(v1, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME))
    apply_install(plan_install(v2, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME))
    rolled = rollback_install(first.lock.digest, paths=paths, lock_store=store)
    assert rolled.lock.version == "1.0.0"
    assert (paths.commands / "review.md").read_text(encoding="utf-8") == "v1"
    uninstall = plan_uninstall(rolled.lock, paths=paths, lock_store=store)
    apply_uninstall(uninstall)
    assert json.loads(paths.config_file.read_text(encoding="utf-8"))["theme"] == "dark"
    assert not (paths.commands / "review.md").exists()


def test_stale_plan_is_rejected_before_writes(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    plan = plan_install(source, paths=paths, lock_store=store, mcp_registry=registry, installed_at=FIXED_TIME)
    target = paths.commands / "review.md"
    target.parent.mkdir(parents=True)
    target.write_text("racer", encoding="utf-8")
    with pytest.raises(OpenCodeConfigConflict, match="stale"):
        apply_install(plan)
    assert target.read_text(encoding="utf-8") == "racer"


def test_mcp_json_pointer_is_owned_and_uninstall_preserves_siblings(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    _register_echo_entrypoint(source, registry)
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text('{"theme":"dark"}\n', encoding="utf-8")

    plan = plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    assert any(item.json_pointer == "/mcp/echo" for item in plan.mutations)
    installed = apply_install(plan)
    config = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert config["theme"] == "dark"
    assert config["mcp"]["echo"]["type"] == "local"

    apply_uninstall(plan_uninstall(installed.lock, paths=paths, lock_store=store))
    assert json.loads(paths.config_file.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_failed_apply_restores_targets_and_leaves_current_lock_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import skillify.agent.opencode_config as adapter

    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    plan = plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    original_apply = adapter._apply_target_mutations

    def fail_after_first_write(paths_arg, mutations):
        first = (mutations[0],)
        original_apply(paths_arg, first)
        raise OSError("injected failure")

    monkeypatch.setattr(adapter, "_apply_target_mutations", fail_after_first_write)
    with pytest.raises(OSError, match="injected"):
        apply_install(plan)

    assert not (paths.root / plan.mutations[0].path).exists()
    assert store.read_current(CapabilityKind.SKILL, "approved", "reviewer") is None


def test_lock_publish_failure_after_replace_restores_files_and_current_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    plan = plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    original_write = store.write_current
    failed = False

    def publish_then_fail(lock):
        nonlocal failed
        result = original_write(lock)
        if not failed:
            failed = True
            raise OSError("post-publish failure")
        return result

    monkeypatch.setattr(store, "write_current", publish_then_fail)
    with pytest.raises(OSError, match="post-publish"):
        apply_install(plan)

    assert all(not (paths.root / item.path).exists() for item in plan.mutations)
    assert store.read_current(CapabilityKind.SKILL, "approved", "reviewer") is None


def test_lock_remove_failure_after_unlink_restores_files_and_current_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    installed = apply_install(plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    uninstall = plan_uninstall(installed.lock, paths=paths, lock_store=store)
    original_remove = store.remove_current
    failed = False

    def remove_then_fail(lock):
        nonlocal failed
        result = original_remove(lock)
        if not failed:
            failed = True
            raise OSError("post-remove failure")
        return result

    monkeypatch.setattr(store, "remove_current", remove_then_fail)
    with pytest.raises(OSError, match="post-remove"):
        apply_uninstall(uninstall)

    assert all((paths.root / item.path).is_file() for item in uninstall.mutations)
    assert store.read_current(CapabilityKind.SKILL, "approved", "reviewer") == installed.lock


def test_raced_user_file_is_not_overwritten_or_removed_during_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import skillify.agent.opencode_config as adapter

    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    plan = plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    target = paths.root / plan.mutations[0].path
    original_snapshots = adapter._whole_target_snapshots

    def race_after_snapshot(paths_arg, mutations):
        snapshots = original_snapshots(paths_arg, mutations)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("raced-user-content", encoding="utf-8")
        return snapshots

    monkeypatch.setattr(adapter, "_whole_target_snapshots", race_after_snapshot)
    with pytest.raises(OpenCodeConfigError, match="rollback"):
        apply_install(plan)
    assert target.read_text(encoding="utf-8") == "raced-user-content"
    assert store.read_current(CapabilityKind.SKILL, "approved", "reviewer") is None


def test_snapshot_directories_are_private_even_when_precreated_permissively(
    tmp_path: Path,
) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    (paths.cache_root / "snapshots").mkdir(parents=True, mode=0o755)
    (paths.cache_root / "snapshots").chmod(0o755)
    installed = apply_install(plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    assert paths.cache_root.stat().st_mode & 0o777 == 0o700
    assert (paths.cache_root / "snapshots").stat().st_mode & 0o777 == 0o700
    assert (
        paths.cache_root / "snapshots" / installed.lock.digest
    ).stat().st_mode & 0o777 == 0o700


def test_update_symlink_type_race_is_restored_without_hidden_displacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1 = _bundle(tmp_path, version="1.0.0", command="v1")
    v2 = _bundle(tmp_path, version="2.0.0", command="v2")
    paths, store, registry = _roots(tmp_path)
    apply_install(plan_install(
        v1, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    plan = plan_install(
        v2, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    target = paths.commands / "review.md"
    user_file = tmp_path / "user-race.txt"
    user_file.write_text("user", encoding="utf-8")
    original_rename = os.rename
    raced = False

    def race_before_quarantine(source, destination, *args, **kwargs):
        nonlocal raced
        if source == "review.md" and not raced:
            raced = True
            target.unlink()
            target.symlink_to(user_file)
        return original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", race_before_quarantine)
    with pytest.raises(OpenCodeConfigError, match="rollback"):
        apply_install(plan)

    assert target.is_symlink()
    assert target.resolve() == user_file
    assert list(target.parent.glob(".review.md.*.old")) == []


def test_uninstall_symlink_type_race_is_restored_without_hidden_displacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _bundle(tmp_path)
    paths, store, registry = _roots(tmp_path)
    installed = apply_install(plan_install(
        source, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    plan = plan_uninstall(installed.lock, paths=paths, lock_store=store)
    target = paths.commands / "review.md"
    user_file = tmp_path / "uninstall-user-race.txt"
    user_file.write_text("user", encoding="utf-8")
    original_rename = os.rename
    raced = False

    def race_before_quarantine(source_name, destination, *args, **kwargs):
        nonlocal raced
        if source_name == "review.md" and not raced:
            raced = True
            target.unlink()
            target.symlink_to(user_file)
        return original_rename(source_name, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", race_before_quarantine)
    with pytest.raises(OpenCodeConfigError, match="rollback"):
        apply_uninstall(plan)

    assert target.is_symlink()
    assert target.resolve() == user_file
    assert list(target.parent.glob(".review.md.*.old")) == []
    assert store.read_current(CapabilityKind.SKILL, "approved", "reviewer") == installed.lock


def test_directory_type_race_is_preserved_under_reported_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v1 = _bundle(tmp_path, version="1.0.0", command="v1")
    v2 = _bundle(tmp_path, version="2.0.0", command="v2")
    paths, store, registry = _roots(tmp_path)
    apply_install(plan_install(
        v1, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    ))
    plan = plan_install(
        v2, paths=paths, lock_store=store, mcp_registry=registry,
        installed_at=FIXED_TIME,
    )
    target = paths.commands / "review.md"
    original_rename = os.rename
    raced = False

    def race_before_quarantine(source_name, destination, *args, **kwargs):
        nonlocal raced
        if source_name == "review.md" and not raced:
            raced = True
            target.unlink()
            target.mkdir()
            (target / "user.txt").write_text("user", encoding="utf-8")
        return original_rename(source_name, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", race_before_quarantine)
    with pytest.raises(OpenCodeConfigError) as raised:
        apply_install(plan)

    hidden = list(target.parent.glob(".review.md.*.old"))
    assert len(hidden) == 1
    assert (hidden[0] / "user.txt").read_text(encoding="utf-8") == "user"
    assert hidden[0].name in str(raised.value)
