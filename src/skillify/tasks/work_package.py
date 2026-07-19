"""User-confirmable work packages; execution remains provider-managed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


def _names(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{field} must be a string list")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must be unique")
    return tuple(value)


@dataclass(frozen=True)
class WorkPackage:
    package_id: str
    task_id: str
    objective: str
    allowed_paths: tuple[str, ...]
    dependencies: tuple[str, ...]
    access: str
    recommended_skills: tuple[str, ...]
    recommended_mcp: tuple[str, ...]
    acceptance_commands: tuple[str, ...]
    parallelizable: bool
    confirmed: bool = False
    depends_on: tuple[str, ...] = ()
    read_only: bool = False
    verification: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WorkPackage":
        dependencies = _names(value.get("dependsOn", value.get("dependencies", [])), "dependsOn")
        verification = _names(
            value.get("verification", value.get("acceptanceCommands", [])), "verification",
        )
        read_only = value.get("readOnly", value.get("access") == "read")
        package = cls(
            package_id=value.get("packageId", ""), task_id=value.get("taskId", ""),
            objective=value.get("objective", ""),
            allowed_paths=_names(value.get("allowedPaths", []), "allowedPaths"),
            dependencies=dependencies,
            access="read" if read_only else value.get("access", ""),
            recommended_skills=_names(value.get("recommendedSkills", []), "recommendedSkills"),
            recommended_mcp=_names(value.get("recommendedMcp", []), "recommendedMcp"),
            acceptance_commands=verification,
            parallelizable=value.get("parallelizable", False),
            confirmed=value.get("confirmed", False),
            depends_on=dependencies, read_only=read_only, verification=verification,
        )
        if not package.package_id or not package.task_id or not package.objective.strip():
            raise ValueError("work package identity and objective are required")
        if not package.allowed_paths or any(
            PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts
            for path in package.allowed_paths
        ):
            raise ValueError("work package allowedPaths must be relative and bounded")
        if package.access not in {"read", "write"}:
            raise ValueError("work package access must be read or write")
        if (
            not isinstance(package.parallelizable, bool)
            or not isinstance(package.confirmed, bool)
            or not isinstance(package.read_only, bool)
        ):
            raise ValueError("work package flags must be booleans")
        if package.package_id in package.dependencies:
            raise ValueError("work package cannot depend on itself")
        return package

    def to_dict(self) -> dict[str, Any]:
        return {
            "packageId": self.package_id, "taskId": self.task_id, "objective": self.objective,
            "allowedPaths": list(self.allowed_paths), "dependencies": list(self.dependencies),
            "access": self.access, "recommendedSkills": list(self.recommended_skills),
            "recommendedMcp": list(self.recommended_mcp),
            "acceptanceCommands": list(self.acceptance_commands),
            "parallelizable": self.parallelizable, "confirmed": self.confirmed,
            "dependsOn": list(self.depends_on or self.dependencies),
            "readOnly": self.read_only or self.access == "read",
            "verification": list(self.verification or self.acceptance_commands),
        }


def validate_delegation_result(mode: str, packages: tuple[WorkPackage, ...]) -> None:
    if mode not in {"adaptive", "suggested", "required"}:
        raise ValueError("delegation mode is invalid")
    identifiers = {package.package_id for package in packages}
    if len(identifiers) != len(packages):
        raise ValueError("work package ids must be unique")
    if any(not set(package.depends_on or package.dependencies) <= identifiers for package in packages):
        raise ValueError("work package dependency is unknown")
    if mode == "required" and len(packages) < 2:
        raise ValueError("required delegation needs at least two independent work packages")
