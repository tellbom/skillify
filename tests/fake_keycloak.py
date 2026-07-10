"""A minimal in-process fake Keycloak JWKS endpoint + token minting, for testing M4's
Keycloak JWT validation (skillify/web/auth.py) without a real Keycloak server.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url_uint(value: int) -> str:
    n_bytes = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")


class FakeKeycloak:
    def __init__(self, server: HTTPServer, realm: str):
        self._server = server
        self.realm = realm
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key-1"

    @property
    def realm_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/realms/{self.realm}"

    def jwks(self) -> dict:
        public_numbers = self.private_key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "kid": self.kid,
                    "use": "sig",
                    "alg": "RS256",
                    "n": _b64url_uint(public_numbers.n),
                    "e": _b64url_uint(public_numbers.e),
                }
            ]
        }

    def mint_token(self, *, audience: str = "skillify-web", subject: str = "u001", extra_claims: dict | None = None, expires_in: int = 300) -> str:
        now = int(time.time())
        claims = {
            "iss": self.realm_url,
            "aud": audience,
            "sub": subject,
            "preferred_username": subject,
            "iat": now,
            "exp": now + expires_in,
        }
        claims.update(extra_claims or {})
        return jwt.encode(claims, self.private_key, algorithm="RS256", headers={"kid": self.kid})


class _Handler(BaseHTTPRequestHandler):
    server: "_FakeKeycloakServer"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        expected = f"/realms/{self.server.fake.realm}/protocol/openid-connect/certs"
        if self.path == expected:
            body = json.dumps(self.server.fake.jwks()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


class _FakeKeycloakServer(HTTPServer):
    fake: FakeKeycloak


@pytest.fixture()
def fake_keycloak():
    server = _FakeKeycloakServer(("127.0.0.1", 0), _Handler)
    server.fake = FakeKeycloak(server, realm="test")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.fake
    finally:
        server.shutdown()
        thread.join(timeout=2)
