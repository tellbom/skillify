from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from skillify.agent.shogun.credentials import EnvironmentCredentialBroker, PaneCredentialInjector


def test_environment_broker_resolves_only_the_approved_named_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-secret")
    broker = EnvironmentCredentialBroker(("DEEPSEEK_API_KEY",))

    credential = broker.credential(
        "deepseek-api-key", "env://DEEPSEEK_API_KEY", frozenset(),
    )

    assert credential.value == "unit-test-secret"
    assert "unit-test-secret" not in json.dumps(broker.__dict__, default=list)
    with pytest.raises(PermissionError, match="not approved"):
        broker.credential("other", "env://OTHER", frozenset())
    with pytest.raises(PermissionError, match="do not accept scopes"):
        broker.credential(
            "deepseek-api-key", "env://DEEPSEEK_API_KEY", frozenset({"model.admin"}),
        )


def test_environment_broker_fails_closed_when_value_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(PermissionError, match="unavailable"):
        EnvironmentCredentialBroker(("DEEPSEEK_API_KEY",)).credential(
            "deepseek-api-key", "env://DEEPSEEK_API_KEY", frozenset(),
        )


@pytest.mark.skipif(os.name == "nt", reason="Unix socket path gate is Linux-only")
def test_credential_socket_fits_linux_limit_under_a_long_team_cache_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-secret")
    broker = EnvironmentCredentialBroker(("DEEPSEEK_API_KEY",))
    injector = PaneCredentialInjector(executables={})
    run_dir = tmp_path / ("x" * 70)

    channel = injector.prepare(
        {"DEEPSEEK_API_KEY": "env://DEEPSEEK_API_KEY"},
        broker=broker, run_dir=run_dir,
    )
    try:
        assert len(os.fsencode(channel.socket_path)) < 108
        assert channel.socket_path.parent == Path(tempfile.gettempdir())
        assert channel.socket_path.name.startswith("skillify-")
    finally:
        injector.destroy(channel)


def test_opencode_launcher_pins_pane_agent_across_new_sessions(tmp_path: Path) -> None:
    injector = PaneCredentialInjector()
    launcher = tmp_path / "opencode"

    injector._write_launcher(launcher, "/opt/opencode", tmp_path / "broker.sock")

    source = launcher.read_text(encoding="utf-8")
    assert '"default_agent"' in source
    assert '"@agent_id"' in source
    assert 'environment["OPENCODE_CONFIG_CONTENT"]' in source
    assert 'environment["OPENCODE_CONFIG_DIR"]' in source
    assert 'permission["external_directory"]' in source
