"""Pydantic response models for the community-site API (T3.1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SkillSummary(BaseModel):
    namespace: str
    name: str
    version: str
    description: str
    author: str
    tags: list[str]
    publishedAt: datetime


class SkillDetail(SkillSummary):
    versions: list[str]
    readme: str | None
    skillMd: str | None
    tarballUrl: str | None
    checksumUrl: str | None
    installCommand: str
    agentPrompt: str
    installCount: int
    ratingAverage: float | None
    ratingCount: int
    starCount: int
    starred: bool
    subscribed: bool


class SearchResult(BaseModel):
    """C-4: pagination wrapper for `GET /api/skills` / `GET /api/search` — `total` is the
    full matching count (not just `len(items)`), so the frontend can compute page count."""

    items: list[SkillSummary]
    total: int
    page: int
    pageSize: int


class InstallInfo(BaseModel):
    installCommand: str
    agentPrompt: str


class UploadResponse(BaseModel):
    namespace: str
    name: str
    version: str
    releaseUrl: str
    indexError: str | None = None


class PublishBuildIn(BaseModel):
    expectedRevision: int
    confirmed: bool


class PublishBuildOut(UploadResponse):
    buildId: str
    revision: int


class GuidedBuildIn(BaseModel):
    manifest: dict[str, Any] = Field(default_factory=dict)
    skillMd: str = ""


class BuildUpdateIn(BaseModel):
    expectedRevision: int
    manifest: dict[str, Any] | None = None
    skillMd: str | None = None


class BuildTreeItem(BaseModel):
    path: str
    type: str
    size: int | None = None


class ValidationIssueOut(BaseModel):
    path: str
    message: str


class BuildPreviewOut(BaseModel):
    buildId: str
    sourceType: str
    revision: int
    status: str
    expiresAt: datetime
    manifest: dict[str, Any]
    manifestYaml: str
    skillMd: str
    tree: list[BuildTreeItem]
    detectedFacts: dict[str, Any]
    missingFields: list[str]
    unconfirmedFields: list[str]
    issues: list[ValidationIssueOut]
    publishable: bool


class ExternalCandidateOut(BaseModel):
    candidateId: str
    rootPath: str
    frontmatter: dict[str, Any]
    detectedPaths: list[str]
    pythonRequirements: list[str]
    issues: list[ValidationIssueOut]


class ExternalScanOut(BaseModel):
    scanId: str
    expiresAt: datetime
    candidates: list[ExternalCandidateOut]


class ExternalSelectionIn(BaseModel):
    candidateIds: list[str]


class ExternalSelectionOut(BaseModel):
    builds: list[BuildPreviewOut]


class CommentIn(BaseModel):
    body: str
    parentId: int | None = None


class CommentOut(BaseModel):
    id: int
    namespace: str
    name: str
    author: str
    body: str
    createdAt: datetime
    parentId: int | None = None
    deleted: bool = False


class RatingIn(BaseModel):
    score: int


class LeaderboardEntry(BaseModel):
    namespace: str
    name: str
    description: str
    installCount: int
    ratingAverage: float | None
    ratingCount: int
    publishedAt: datetime


class RatingOut(BaseModel):
    namespace: str
    name: str
    ratingAverage: float | None
    ratingCount: int
    yourScore: int


class EventIn(BaseModel):
    eventType: str  # "install" | "run"
    version: str
    success: bool | None = None
    machineId: str | None = None


class VersionInfo(BaseModel):
    version: str
    publishedAt: datetime
    yanked: bool
    releaseNotes: str | None = None


class YankOut(BaseModel):
    version: str
    yanked: bool


class VersionDiff(BaseModel):
    added: list[str]
    removed: list[str]
    modified: list[str]


class MyNamespaceOut(BaseModel):
    namespace: str
    claimedAt: datetime


class PublishJobOut(BaseModel):
    namespace: str
    name: str
    version: str
    status: str
    errorMessage: str | None = None
    createdAt: datetime
    updatedAt: datetime


class MyUsageStats(BaseModel):
    totalSkills: int
    totalInstalls: int
    installsBySkill: dict[str, int]


class StarOut(BaseModel):
    starred: bool
    starCount: int


class SubscriptionOut(BaseModel):
    subscribed: bool


class MySubscriptionOut(BaseModel):
    namespace: str
    name: str
    latestVersion: str
    publishedAt: datetime
