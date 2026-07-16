from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from skillify.credentials.broker import AuthProfile, CredentialBroker
from skillify.credentials.identities import AccessCredential, IdentityKind


NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)


class UserIdentity:
    calls = 0

    def acquire_user_token(self, audience, scopes):
        self.calls += 1
        return AccessCredential("user-secret", audience, scopes, NOW + timedelta(minutes=5))


class ServiceIdentity:
    calls = 0

    def acquire_service_token(self, audience, scopes):
        self.calls += 1
        return AccessCredential("service-secret", audience, scopes, NOW + timedelta(minutes=5))


def broker(identity=IdentityKind.USER_DELEGATED):
    return CredentialBroker(
        (AuthProfile("orders", identity, "local://orders/current-user", "orders-api", frozenset({"orders.read"})),),
        user_identity=UserIdentity(), service_identity=ServiceIdentity(), now=lambda: NOW,
    )


def test_broker_resolves_profile_checks_scope_and_caches_short_token() -> None:
    value = broker()
    first = value.credential("orders", "local://orders/current-user", frozenset({"orders.read"}))
    second = value.credential("orders", "local://orders/current-user", frozenset({"orders.read"}))

    assert first is second
    assert first.value == "user-secret"
    serialized = json.dumps(value.audit())
    assert "user-secret" not in serialized
    assert "orders-api" in serialized


def test_broker_separates_service_account_and_rejects_unapproved_or_machine_identity() -> None:
    assert broker(IdentityKind.SERVICE_ACCOUNT).credential(
        "orders", "local://orders/current-user", frozenset({"orders.read"})
    ).value == "service-secret"
    with pytest.raises(PermissionError, match="approved"):
        broker().credential("orders", "local://orders/current-user", frozenset())
    with pytest.raises(PermissionError, match="cannot be used"):
        broker(IdentityKind.ENDPOINT).credential(
            "orders", "local://orders/current-user", frozenset({"orders.read"})
        )


@pytest.mark.parametrize("reason", ["cancel", "exit", "timeout"])
def test_broker_clears_cached_credentials_on_terminal_paths(reason: str) -> None:
    value = broker()
    value.credential("orders", "local://orders/current-user", frozenset({"orders.read"}))
    value.clear(reason)

    assert value.audit()[-1] == {"event": "credential.cleared", "reason": reason, "count": 1}
