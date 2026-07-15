from __future__ import annotations

import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers.opencode import OpenCodeProvider

pytestmark = pytest.mark.skip(reason="requires test-env: real OpenCode binary, model endpoint, and target Linux")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_real_opencode_is_localhost_only_and_leaves_no_process(tmp_path: Path) -> None:
    workspace = (tmp_path / "repo").resolve(); workspace.mkdir()
    subprocess.run(["git", "init", str(workspace)], check=True, capture_output=True)
    runtime = ModelRuntimeConfig(
        provider=os.environ["TEST_OPENCODE_PROVIDER"],
        endpoint=os.environ["TEST_OPENCODE_MODEL_ENDPOINT"],
        model=os.environ["TEST_OPENCODE_MODEL"],
        allowed_endpoint_hosts=(os.environ["TEST_OPENCODE_MODEL_HOST"],),
        credential_env_names=(os.environ["TEST_OPENCODE_CREDENTIAL_ENV"],),
    )
    provider = OpenCodeProvider(
        port_factory=_free_port,
        clock=lambda: datetime.now(timezone.utc),
    )
    handle = provider.start(ProviderStartSpec(workspace, (workspace,), tmp_path / "config", runtime))
    try:
        session = provider.create_session(handle, TaskSpec("smoke-1", "Inspect README, create marker.txt, and run the repository test command."))
        events = list(provider.stream_events(handle, session))
        assert events[-1].state.value == "succeeded"
        listeners = subprocess.run(["ss", "-ltnp"], check=True, capture_output=True, text=True).stdout
        owned = [line for line in listeners.splitlines() if f"pid={handle.process_id}," in line]
        assert owned and all("127.0.0.1:" in line and "0.0.0.0:" not in line for line in owned)
    finally:
        provider.stop(handle)
    with pytest.raises(ProcessLookupError):
        os.kill(handle.process_id, 0)
