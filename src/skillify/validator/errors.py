"""Validation result types shared across the validator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationIssue:
    """A single, actionable validation failure.

    `path` is a dotted/segment path pointing at the offending field or file
    (e.g. "skill.yaml:dependencies.python[0]", "SKILL.md:frontmatter.name",
    "directory:requirements.txt"), never a bare "invalid" with no location.
    """

    path: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.path}: {self.message}"


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path=path, message=message))

    def extend(self, other: "ValidationResult") -> None:
        self.issues.extend(other.issues)

    def __bool__(self) -> bool:
        return self.ok
