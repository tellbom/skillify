"""Independent endpoint-machine authentication for outbound Bridge calls."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Header, HTTPException

from skillify.common.config import load_config


def issue_endpoint_token(endpoint_id: str, owner: str, secret: bytes) -> str:
    payload = f"{endpoint_id}.{owner}"
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def require_endpoint_machine(authorization: str | None = Header(default=None)) -> dict[str, str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing endpoint bearer token")
    secret = load_config().endpoint_device_secret
    if not secret:
        raise HTTPException(status_code=503, detail="endpoint machine identity is not configured")
    token = authorization.split(" ", 1)[1]
    try:
        endpoint_id, owner, signature = token.split(".", 2)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid endpoint token") from exc
    expected = issue_endpoint_token(endpoint_id, owner, secret.encode()).rsplit(".", 1)[1]
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid endpoint token")
    return {"endpoint_id": endpoint_id, "owner": owner, "identity_kind": "endpoint"}
