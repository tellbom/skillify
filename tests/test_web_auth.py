"""Tests for M4a — Keycloak JWT bearer validation."""

from __future__ import annotations

import time

import pytest

from skillify.common.config import SkillifyConfig
from skillify.web.auth import KeycloakNotConfiguredError, validate_bearer_token
from tests.fake_keycloak import fake_keycloak  # noqa: F401


def test_valid_token_is_accepted(fake_keycloak) -> None:
    cfg = SkillifyConfig(keycloak_realm_url=fake_keycloak.realm_url, keycloak_audience="skillify-web")
    token = fake_keycloak.mint_token(audience="skillify-web", subject="jane")

    claims = validate_bearer_token(token, cfg)
    assert claims["sub"] == "jane"
    assert claims["preferred_username"] == "jane"


def test_wrong_audience_is_rejected(fake_keycloak) -> None:
    import jwt

    cfg = SkillifyConfig(keycloak_realm_url=fake_keycloak.realm_url, keycloak_audience="skillify-web")
    token = fake_keycloak.mint_token(audience="some-other-app")

    with pytest.raises(jwt.InvalidAudienceError):
        validate_bearer_token(token, cfg)


def test_expired_token_is_rejected(fake_keycloak) -> None:
    import jwt

    cfg = SkillifyConfig(keycloak_realm_url=fake_keycloak.realm_url, keycloak_audience="skillify-web")
    token = fake_keycloak.mint_token(audience="skillify-web", expires_in=-10)

    with pytest.raises(jwt.ExpiredSignatureError):
        validate_bearer_token(token, cfg)


def test_tampered_token_is_rejected(fake_keycloak) -> None:
    import jwt

    cfg = SkillifyConfig(keycloak_realm_url=fake_keycloak.realm_url, keycloak_audience="skillify-web")
    token = fake_keycloak.mint_token(audience="skillify-web")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

    with pytest.raises(jwt.PyJWTError):
        validate_bearer_token(tampered, cfg)


def test_missing_realm_config_raises() -> None:
    cfg = SkillifyConfig()
    with pytest.raises(KeycloakNotConfiguredError):
        validate_bearer_token("whatever", cfg)


def test_no_audience_configured_skips_audience_check(fake_keycloak) -> None:
    cfg = SkillifyConfig(keycloak_realm_url=fake_keycloak.realm_url, keycloak_audience=None)
    token = fake_keycloak.mint_token(audience="anything-at-all")

    claims = validate_bearer_token(token, cfg)
    assert claims["aud"] == "anything-at-all"
