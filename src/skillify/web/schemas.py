"""Pydantic response models for the community-site API (T3.1)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


class InstallInfo(BaseModel):
    installCommand: str
    agentPrompt: str


class UploadResponse(BaseModel):
    namespace: str
    name: str
    version: str
    releaseUrl: str
    indexError: str | None = None


class CommentIn(BaseModel):
    body: str


class CommentOut(BaseModel):
    id: int
    namespace: str
    name: str
    author: str
    body: str
    createdAt: datetime


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
