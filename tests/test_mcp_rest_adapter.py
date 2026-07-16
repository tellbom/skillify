from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from skillify.mcp.rest.adapter import RestAdapter, RestAdapterError, RestTool


class Credential:
    def token(self, credential_ref, scopes):
        assert credential_ref == "local://tickets/current-user"
        assert scopes
        return "test-secret-token"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path.startswith("/tickets/42")
        assert self.headers["Authorization"] == "Bearer test-secret-token"
        body = json.dumps({"id": 42, "title": "Broken parser", "internal": "hidden"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        value = json.loads(self.rfile.read(length))
        body = json.dumps({"created": bool(value["body"]), "token": "must-not-return"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


@pytest.fixture
def server():
    value = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    try:
        yield value
    finally:
        value.shutdown()
        thread.join()


def adapter(server, scopes=frozenset({"ticket:read", "ticket:write"})):
    port = server.server_address[1]
    return RestAdapter(
        f"http://127.0.0.1:{port}",
        allowed_target=("127.0.0.1", port, "http"),
        credential_ref="local://tickets/current-user",
        approved_scopes=scopes,
        credential_provider=Credential(),
        tools=(
            RestTool("ticket.read", "GET", "/tickets/42", frozenset({"ticket:read"}), frozenset({"id", "title"})),
            RestTool("ticket.comment", "POST", "/tickets/42/comments", frozenset({"ticket:write"}), frozenset({"created"}), write=True),
        ),
    )


def test_rest_adapter_maps_fixed_tool_and_trims_response(server) -> None:
    assert adapter(server).invoke("ticket.read", {"view": "summary"}) == {
        "id": 42, "title": "Broken parser",
    }
    assert adapter(server).invoke("ticket.comment", {"body": "investigating"}) == {
        "created": True,
    }


def test_rest_adapter_enforces_network_scope_and_stable_errors(server) -> None:
    port = server.server_address[1]
    with pytest.raises(ValueError, match="network allowlist"):
        RestAdapter(
            f"http://127.0.0.1:{port}",
            allowed_target=("other.internal", 443, "https"),
            credential_ref="local://tickets/current-user",
            approved_scopes=frozenset(), credential_provider=Credential(),
            tools=(RestTool("ticket.read", "GET", "/tickets/42", frozenset(), frozenset()),),
        )
    with pytest.raises(PermissionError, match="scopes"):
        adapter(server, frozenset({"ticket:read"})).invoke("ticket.comment", {"body": "x"})
    with pytest.raises(RestAdapterError, match="unknown"):
        adapter(server).invoke("execute_anything", {"url": "https://public.example"})
