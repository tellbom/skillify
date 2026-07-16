"""Endpoint-side credential broker with fakeable identity providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from skillify.credentials.identities import (
    AccessCredential,
    IdentityKind,
    ServiceAccountIdentity,
    UserDelegatedIdentity,
)


@dataclass(frozen=True)
class AuthProfile:
    name: str
    identity: IdentityKind
    credential_ref: str
    audience: str
    scopes: frozenset[str]


class CredentialBroker:
    def __init__(
        self,
        profiles: tuple[AuthProfile, ...],
        *,
        user_identity: UserDelegatedIdentity,
        service_identity: ServiceAccountIdentity,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.profiles = {profile.name: profile for profile in profiles}
        self.user_identity = user_identity
        self.service_identity = service_identity
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._cache: dict[str, AccessCredential] = {}
        self._audit: list[dict[str, object]] = []

    def credential(
        self,
        auth_profile: str,
        credential_ref: str,
        approved_scopes: frozenset[str],
    ) -> AccessCredential:
        try:
            profile = self.profiles[auth_profile]
        except KeyError as exc:
            raise PermissionError("auth profile is not registered") from exc
        if profile.credential_ref != credential_ref:
            raise PermissionError("credential reference does not match auth profile")
        if not profile.scopes <= approved_scopes:
            raise PermissionError("credential scopes were not approved")
        current = self._cache.get(profile.name)
        if current is None or current.expires_at <= self.now() + timedelta(seconds=30):
            if profile.identity is IdentityKind.USER_DELEGATED:
                current = self.user_identity.acquire_user_token(profile.audience, profile.scopes)
            elif profile.identity is IdentityKind.SERVICE_ACCOUNT:
                current = self.service_identity.acquire_service_token(profile.audience, profile.scopes)
            else:
                raise PermissionError("web and endpoint identities cannot be used as business credentials")
            if current.audience != profile.audience or current.scopes != profile.scopes:
                raise PermissionError("issued credential audience or scopes do not match")
            self._cache[profile.name] = current
            self._audit.append({
                "profile": profile.name,
                "identity": profile.identity.value,
                "audience": profile.audience,
                "scopes": sorted(profile.scopes),
                "event": "credential.acquired",
            })
        return current

    def clear(self, reason: str) -> None:
        count = len(self._cache)
        self._cache.clear()
        self._audit.append({"event": "credential.cleared", "reason": reason, "count": count})

    def audit(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._audit)
