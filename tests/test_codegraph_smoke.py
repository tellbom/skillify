from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="requires test-env: approved CodeGraph bundle and target Linux repositories")


def test_real_codegraph_install_index_and_two_provider_mcp_calls() -> None:
    """Executed from the convergence E2E checklist in the target environment."""
