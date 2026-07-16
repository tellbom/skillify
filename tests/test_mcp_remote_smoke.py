from __future__ import annotations

import os
import urllib.request

import pytest


pytestmark = pytest.mark.skip(reason="requires test-env: approved internal remote MCP HTTPS endpoint")


def test_approved_remote_mcp_https_endpoint() -> None:
    url = os.environ["SKILLIFY_TEST_MCP_URL"]
    token = os.environ["SKILLIFY_TEST_MCP_TOKEN"]
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - gated test environment
        assert response.status == 200
