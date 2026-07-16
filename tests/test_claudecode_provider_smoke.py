import pytest


pytestmark = pytest.mark.skip(reason="requires test-env: real Claude Code, model endpoint and target Linux")


def test_real_claude_code_headless_provider_lifecycle() -> None:
    """Executed from the convergence E2E checklist in the target environment."""
