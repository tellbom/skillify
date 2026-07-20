from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest

if os.name != "posix":
    pytest.skip("Shogun provider is Linux-only", allow_module_level=True)

from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec, TaskSpec
from skillify.agent.providers import shogun as shogun_module
from skillify.agent.providers.shogun import ShogunProvider
from skillify.agent.shogun.contract import COMMAND_FILE
from skillify.agent.shogun.fake_runtime import FakeRuntime
from skillify.credentials.identities import AccessCredential


class Broker:
    profiles = {
        "model": SimpleNamespace(
            name="model", credential_ref="local://model", scopes=frozenset({"model.invoke"}),
        ),
    }

    def credential(self, profile, reference, scopes):
        return AccessCredential(
            "test-only-secret", "model", scopes,
            datetime.now(timezone.utc) + timedelta(minutes=5),
        )

    def clear(self, reason):
        pass


def test_provider_scans_the_written_queue_dir(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "bundle"
    install.mkdir()
    entrypoint = install / "shutsujin_departure.sh"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o755)
    manifest = tmp_path / "manifest.json"
    artifact = tmp_path / "bundle.tar.gz"
    manifest.write_text("{}", encoding="utf-8")
    artifact.write_bytes(b"test")
    monkeypatch.setattr(shogun_module, "load_manifest", lambda _: {})
    monkeypatch.setattr(shogun_module, "require_installable", lambda _: None)
    monkeypatch.setattr(shogun_module, "verify_artifact", lambda *_: None)
    monkeypatch.setattr(shogun_module, "check_bundle_layout", lambda *_: None)
    monkeypatch.setattr(
        shogun_module, "check_host_dependencies",
        lambda _: SimpleNamespace(available=True, detail="ready"),
    )
    runtime = FakeRuntime()
    provider = ShogunProvider(
        manifest_path=manifest, artifact_path=artifact, install_root=install,
        cache_root=tmp_path / "cache", runtime=runtime, credential_broker=Broker(),
    )
    workspace = (tmp_path / "workspace").resolve()
    workspace.mkdir()
    run_dir = (tmp_path / "run").resolve()
    spec = ProviderStartSpec(
        workspace, (workspace,), run_dir,
        ModelRuntimeConfig(
            "test", "https://model.internal", "model", ("model.internal",), ("MODEL_TOKEN",),
        ),
        execution_mode="team", preferred_cli="opencode",
        credential_refs={"MODEL_TOKEN": "local://model"},
    )

    handle = provider.start(spec)
    provider.create_session(handle, TaskSpec("task-1", "test the team"))
    list(provider.stream_events(handle, provider._sessions[next(iter(provider._sessions))]))

    command_path = run_dir / "queue" / COMMAND_FILE
    assert command_path.exists()
    assert ("queue-states", str(command_path.parent)) in runtime.actions
    provider.stop(handle)
