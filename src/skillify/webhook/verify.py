"""Forgejo webhook HMAC signature verification (T2.1c).

Forgejo (like Gitea) signs webhook deliveries as HMAC-SHA256 of the raw request body using
the secret configured on the webhook, sent in `X-Forgejo-Signature` (or the legacy
`X-Gitea-Signature` for older/compat setups) — as a bare hex digest, not GitHub's `sha256=`-
prefixed form, though this accepts the prefixed form too for robustness.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_forgejo_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header:
        return False
    signature = signature_header.removeprefix("sha256=").strip()
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
