"""Keycloak JWT bearer validation for protected FastAPI endpoints (M4).

Originally applied only to write endpoints (skill upload, T4.2); per the M-A decision
(docs/review-m2-m6.md, joint Opus+GPT review) the whole market now requires a logged-in
user, including reads (browse/search/detail/leaderboard/comments) — an SPA-only guard is
bypassable via direct API calls, so this same dependency is applied server-side to those
endpoints too. See TASKS.md's M4 section for the full Keycloak+Rbac.Api integration design:
the Vue3 frontend logs into Keycloak directly and separately bridges to the external .NET
Rbac.Api for menu/route visibility (RBAC controls frontend navigation only — it does not
replace this dependency, which is the real security boundary for the API).
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from skillify.common.config import SkillifyConfig, load_config


class KeycloakNotConfiguredError(Exception):
    pass


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True)


def validate_bearer_token(token: str, cfg: SkillifyConfig) -> dict:
    """Validate a Keycloak-issued JWT (signature + issuer + audience + expiry).
    Returns the decoded claims on success; raises KeycloakNotConfiguredError or a
    jwt.PyJWTError subclass on failure."""
    if not cfg.keycloak_realm_url:
        raise KeycloakNotConfiguredError("keycloak_realm_url not configured")

    realm_url = cfg.keycloak_realm_url.rstrip("/")
    jwks_url = f"{realm_url}/protocol/openid-connect/certs"
    signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)

    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=cfg.keycloak_audience,
        issuer=realm_url,
        options={"require": ["exp", "iat"], "verify_aud": cfg.keycloak_audience is not None},
    )


def require_keycloak_user(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: require a valid Keycloak bearer token, return its decoded claims."""
    cfg = load_config()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        return validate_bearer_token(token, cfg)
    except KeycloakNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
