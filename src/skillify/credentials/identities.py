"""Separated identity contracts for endpoint tasks and business API access."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class IdentityKind(str, Enum):
    WEB_USER = "web-user"
    ENDPOINT = "endpoint"
    USER_DELEGATED = "user-delegated"
    SERVICE_ACCOUNT = "service-account"


@dataclass(frozen=True)
class AccessCredential:
    value: str
    audience: str
    scopes: frozenset[str]
    expires_at: datetime


class WebUserIdentity(Protocol):
    def validate_web_user(self, token: str) -> str: ...


class EndpointMachineIdentity(Protocol):
    def validate_endpoint(self, token: str) -> str: ...


class UserDelegatedIdentity(Protocol):
    def acquire_user_token(self, audience: str, scopes: frozenset[str]) -> AccessCredential: ...


class ServiceAccountIdentity(Protocol):
    def acquire_service_token(self, audience: str, scopes: frozenset[str]) -> AccessCredential: ...
