"""Internal records and errors for preview-first Skill builds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

BuildSourceType = Literal["native_zip", "guided", "external"]
BuildStatus = Literal["needs_input", "ready", "publishing", "published"]

REQUIRED_MANIFEST_FIELDS = (
    "manifestVersion",
    "namespace",
    "name",
    "version",
    "description",
    "author",
    "license",
    "runtime",
    "targets",
)

EXTERNAL_CONFIRMATION_FIELDS = (
    "namespace",
    "name",
    "version",
    "description",
    "author",
    "license",
    "runtime",
    "targets",
    "dependencies",
    "permissions",
    "tags",
)


@dataclass(frozen=True)
class BuildRecord:
    build_id: str
    owner: str
    source_type: BuildSourceType
    revision: int
    status: BuildStatus
    created_at: datetime
    expires_at: datetime
    workspace: Path
    detected_facts: dict[str, Any]
    confirmed_fields: set[str]


class BuildNotFound(Exception):
    """The build is absent, expired, or not owned by the caller."""


class BuildRevisionConflict(Exception):
    def __init__(self, current_revision: int):
        self.current_revision = current_revision
        super().__init__(f"stale build revision; current revision is {current_revision}")


class BuildStateConflict(Exception):
    pass


class BuildNotReady(Exception):
    def __init__(
        self,
        *,
        missing_fields: list[str],
        unconfirmed_fields: list[str],
        issues: list[dict[str, str]],
    ) -> None:
        self.missing_fields = missing_fields
        self.unconfirmed_fields = unconfirmed_fields
        self.issues = issues
        super().__init__("build is not ready to publish")


class InvalidBuildFile(Exception):
    pass


class BuildLimitExceeded(Exception):
    pass
