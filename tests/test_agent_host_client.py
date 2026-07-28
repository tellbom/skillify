from __future__ import annotations

import os
from pathlib import Path

import pytest

from skillify.agent.host_client import host_environment


def test_host_environment_prepends_approved_provider_binary_directory() -> None:
    original = os.environ.get("PATH", "")

    environment = host_environment((Path("/opt/skillify/providers/opencode/bin"),))

    assert environment["PATH"].split(os.pathsep)[0] == "/opt/skillify/providers/opencode/bin"
    assert environment["PATH"].endswith(original)


def test_host_environment_rejects_relative_path_entries() -> None:
    with pytest.raises(ValueError, match="must be absolute"):
        host_environment((Path("providers/bin"),))
