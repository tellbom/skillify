"""Assemble the four declared task permission sources into one strict boundary."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from skillify.agent.permissions import (
    MergedPermissions, PermissionAction, PermissionManifest, merge_permissions,
)
from skillify.tasks.work_package import WorkPackage
from skillify.workflows.pack_config import WorkflowPack


def _combine(policy_id: str, policies: Iterable[PermissionManifest]) -> PermissionManifest | None:
    values = tuple(policies)
    if not values:
        return None
    commands: dict[str, PermissionAction] = {}
    for policy in values:
        for pattern, action in policy.commands.items():
            previous = commands.get(pattern)
            commands[pattern] = action if previous is None else max(
                (previous, action), key=lambda item: item.restriction_rank,
            )
    return PermissionManifest(
        policy_id=policy_id,
        read_paths=tuple(dict.fromkeys(item for policy in values for item in policy.read_paths)),
        write_paths=tuple(dict.fromkeys(item for policy in values for item in policy.write_paths)),
        commands=commands,
        network_domains=tuple(dict.fromkeys(
            item for policy in values for item in policy.network_domains
        )),
        mcp_servers=tuple(dict.fromkeys(item for policy in values for item in policy.mcp_servers)),
        database_resources=tuple(dict.fromkeys(
            item for policy in values for item in policy.database_resources
        )),
        unattended=all(policy.unattended for policy in values),
        confirm=tuple(dict.fromkeys(item for policy in values for item in policy.confirm)),
    )


def _task_policy(packages: tuple[WorkPackage, ...]) -> PermissionManifest:
    read_paths = tuple(dict.fromkeys(path for package in packages for path in package.allowed_paths))
    write_paths = tuple(dict.fromkeys(
        path for package in packages if not package.read_only and package.access != "read"
        for path in package.allowed_paths
    ))
    commands = {
        command: PermissionAction.ALLOW
        for package in packages for command in package.acceptance_commands
    }
    return PermissionManifest(
        policy_id="task:work-packages", read_paths=read_paths, write_paths=write_paths,
        commands=commands,
        mcp_servers=tuple(dict.fromkeys(
            name for package in packages for name in package.recommended_mcp
        )),
        unattended=False, confirm=("write", "command"),
    )


def assemble_task_permissions(
    *, workflow: WorkflowPack,
    skill_permissions: Mapping[str, PermissionManifest],
    mcp_permissions: Mapping[str, PermissionManifest],
    packages: tuple[WorkPackage, ...],
) -> MergedPermissions:
    missing_skills = set(workflow.skills) - set(skill_permissions)
    required_mcp = set(workflow.mcp) | {
        name for package in packages for name in package.recommended_mcp
    }
    missing_mcp = required_mcp - set(mcp_permissions)
    if missing_skills or missing_mcp:
        raise ValueError(
            f"task permission sources are incomplete: skills={sorted(missing_skills)}, "
            f"mcp={sorted(missing_mcp)}"
        )
    skill = _combine(
        "task:skills", (skill_permissions[name] for name in workflow.skills),
    )
    mcp = _combine("task:mcp", (mcp_permissions[name] for name in sorted(required_mcp)))
    sources = tuple(item for item in (skill, workflow.permissions, mcp, _task_policy(packages)) if item)
    return merge_permissions(sources)
