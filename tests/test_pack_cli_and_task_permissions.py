from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml
from typer.testing import CliRunner

from skillify.agent.permissions import (
    OperationKind, OperationRequest, PermissionAction, PermissionManifest,
)
from skillify.cli.main import app
from skillify.packaging.pack import pack_skill
from skillify.tasks.task_permissions import assemble_task_permissions
from skillify.tasks.work_package import WorkPackage
from skillify.workflows import load_workflow_pack


ROOT = Path(__file__).resolve().parents[1]


def test_pack_cli_install_update_rollback_remove_preserves_user_config(
    monkeypatch, tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".opencode/opencode.json"
    config.parent.mkdir()
    config.write_text('{"theme":"dark"}\n', encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setenv("SKILLIFY_AGENT_STATE_DIR", str(state))
    monkeypatch.setenv("SKILLIFY_AGENT_CACHE_DIR", str(tmp_path / "cache"))
    v1 = tmp_path / "v1/feature"
    v2 = tmp_path / "v2/feature"
    shutil.copytree(ROOT / "workflows/feature", v1)
    shutil.copytree(v1, v2)
    manifest = yaml.safe_load((v2 / "skill.yaml").read_text(encoding="utf-8"))
    manifest["version"] = "1.1.0"
    (v2 / "skill.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    workflow = (v2 / "workflow.yaml").read_text(encoding="utf-8")
    (v2 / "workflow.yaml").write_text(workflow + "\n# version two\n", encoding="utf-8")
    runner = CliRunner()
    checksum_v1 = pack_skill(v1, tmp_path / "dist-v1").sha256
    checksum_v2 = pack_skill(v2, tmp_path / "dist-v2").sha256

    installed = runner.invoke(app, [
        "pack", "install", str(v1), "--project", str(project),
        "--commit", "a" * 40, "--checksum", checksum_v1,
    ])
    assert installed.exit_code == 0, installed.output
    v1_digest = re.search(r"lock=([0-9a-f]{64})", installed.output).group(1)
    command = project / ".opencode/commands/feature.md"
    assert command.read_text(encoding="utf-8") == workflow
    assert config.read_text(encoding="utf-8") == '{"theme":"dark"}\n'

    updated = runner.invoke(app, [
        "pack", "update", str(v2), "--project", str(project),
        "--commit", "b" * 40, "--checksum", checksum_v2,
    ])
    assert updated.exit_code == 0, updated.output
    assert command.read_text(encoding="utf-8").endswith("# version two\n")

    rolled_back = runner.invoke(app, [
        "pack", "rollback", v1_digest, "--project", str(project),
    ])
    assert rolled_back.exit_code == 0, rolled_back.output
    assert command.read_text(encoding="utf-8") == workflow

    removed = runner.invoke(app, [
        "pack", "remove", "skillify/feature", "--project", str(project),
    ])
    assert removed.exit_code == 0, removed.output
    assert not command.exists()
    assert config.read_text(encoding="utf-8") == '{"theme":"dark"}\n'


def test_pack_cli_rejects_checksum_that_does_not_match_source(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    runner = CliRunner()

    result = runner.invoke(app, [
        "pack", "install", str(ROOT / "workflows/feature"), "--project", str(project),
        "--commit", "a" * 40, "--checksum", "0" * 64,
    ])

    assert result.exit_code != 0
    assert "checksum does not match" in result.output


def test_real_task_permission_assembly_keeps_workflow_deny_over_later_task_allow(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "feature"
    shutil.copytree(ROOT / "workflows/feature", pack_root)
    manifest_path = pack_root / "skill.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["permissions"]["writePaths"] = []
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    workflow = load_workflow_pack(pack_root)
    allow = PermissionManifest.from_value("skill:allow", {
        "readPaths": ["*"], "writePaths": ["*"],
        "commands": {"pytest *": "allow"},
        "mcpServers": ["codegraph", "forgejo"],
    })
    package = WorkPackage.from_dict({
        "packageId": "implementation", "taskId": "task-1", "objective": "Implement",
        "allowedPaths": ["src/**"], "access": "write",
        "recommendedSkills": [], "recommendedMcp": [],
        "acceptanceCommands": ["pytest *"], "parallelizable": False,
    })
    merged = assemble_task_permissions(
        workflow=workflow,
        skill_permissions={name: allow for name in workflow.skills},
        mcp_permissions={name: allow for name in workflow.mcp}, packages=(package,),
    )

    decision = merged.decide(OperationRequest(
        kind=OperationKind.WRITE_PATH, workspace=tmp_path, path="src/app.py", origin="local",
    ))
    assert decision.action is PermissionAction.DENY
    assert [policy.policy_id for policy in merged.policies] == [
        "task:skills", "workflow:feature-development", "task:mcp", "task:work-packages",
    ]
