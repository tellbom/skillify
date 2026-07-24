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
    installCount: int
    ratingAverage: float | None
    ratingCount: int
    starCount: int


class SkillGovernance(BaseModel):
    compatibleExecutors: list[str] = Field(default_factory=list)
    requiredMcp: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    scanStatus: str = "not-reported"
    examples: list[str] = Field(default_factory=list)
    successRate: float | None = None
    testPassRate: float | None = None
    sampleSize: int = 0
    failureReasons: dict[str, int] = Field(default_factory=dict)
    taskContentCollected: bool = False


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
    governance: SkillGovernance = Field(default_factory=SkillGovernance)


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


class EndpointOut(BaseModel):
    endpointId: str
    label: str
    online: bool
    workspaceAliases: list[str]
    lastSeenAt: datetime


class EndpointTaskCreateIn(BaseModel):
    endpointId: str
    workflowId: str
    workflowVersion: str
    workspaceAlias: str
    inputs: dict[str, Any]
    runtime: str = "opencode"
    executionMode: str = "single"
    preferredCli: str | None = None
    teamPolicy: dict[str, Any] = Field(default_factory=dict)


class EndpointTaskEventOut(BaseModel):
    eventType: str
    occurredAt: datetime
    summary: str | None = None
    testSummary: dict[str, Any] | None = None
    diffStats: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    failureReason: str | None = None
    workerId: str | None = None
    workPackageId: str | None = None
    stage: str | None = None


class WorkPackageIn(BaseModel):
    packageId: str
    taskId: str
    objective: str
    allowedPaths: list[str]
    dependencies: list[str] = Field(default_factory=list)
    access: str
    recommendedSkills: list[str] = Field(default_factory=list)
    recommendedMcp: list[str] = Field(default_factory=list)
    acceptanceCommands: list[str] = Field(default_factory=list)
    parallelizable: bool = False
    confirmed: bool = False
    dependsOn: list[str] = Field(default_factory=list)
    readOnly: bool = False
    verification: list[str] = Field(default_factory=list)


class WorkPackageListIn(BaseModel):
    packages: list[WorkPackageIn]


class EndpointTaskOut(BaseModel):
    taskId: str
    endpointId: str
    workflowId: str
    workflowVersion: str
    delegationMode: str
    workspaceAlias: str
    runtime: str
    executionMode: str = "single"
    collaborationRuntime: str | None = None
    preferredCli: str | None = None
    teamPolicy: dict[str, Any] = Field(default_factory=dict)
    state: str
    approvalRequired: bool
    createdAt: datetime
    updatedAt: datetime
    events: list[EndpointTaskEventOut] = Field(default_factory=list)
    workPackages: list[WorkPackageIn] = Field(default_factory=list)


class EndpointTaskLifecycleIn(BaseModel):
    nonce: str
    stateVersion: int


class EndpointTaskScopeConfirmationIn(EndpointTaskLifecycleIn):
    purpose: str
    aliases: list[str]


class EndpointEventIn(EndpointTaskLifecycleIn):
    eventId: str
    taskId: str
    eventType: str
    occurredAt: datetime
    summary: str | None = None
    testSummary: dict[str, Any] | None = None
    diffStats: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    failureReason: str | None = None
    reasonCode: str | None = None
    workerId: str | None = None
    workPackageId: str | None = None
    stage: str | None = None


class ProviderSessionIn(BaseModel):
    taskId: str
    teamRunId: str | None = None
    workerId: str
    workPackageId: str | None = None
    provider: str
    providerSessionId: str
    runtimeInstanceId: str
    workspace: str
    required: bool = True
    dependsOn: list[str] = Field(default_factory=list)
    resumeMetadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeEventIn(BaseModel):
    eventId: str
    providerSessionId: str
    sequence: int = Field(ge=1)
    eventType: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurredAt: datetime


class AgentInteractionRequestIn(BaseModel):
    providerSessionId: str
    providerRequestId: str
    kind: str
    title: str
    description: str | None = None
    choices: list[dict[str, Any]] = Field(default_factory=list)
    allowFreeText: bool = False
    expiresAt: datetime | None = None


class AgentInteractionResponseIn(BaseModel):
    responseVersion: int = Field(ge=0)
    choice: str | None = None
    answer: str | None = None
    comment: str | None = None


class AgentInteractionAckIn(BaseModel):
    status: str
