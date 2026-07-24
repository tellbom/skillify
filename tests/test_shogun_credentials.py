from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from skillify.agent.shogun.credentials import PaneCredentialInjector
from skillify.credentials.identities import AccessCredential


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"), reason="Shogun credential channel is Linux-only",
)


@dataclass(frozen=True)
class Profile:
    name: str
    credential_ref: str
    scopes: frozenset[str]


class Broker:
    def __init__(self) -> None:
        profile = Profile("model", "vault://model/current", frozenset({"model.invoke"}))
        self.profiles = {profile.name: profile}
        self.calls: list[tuple[str, str, frozenset[str]]] = []
        self.clears: list[str] = []

    def credential(self, profile, reference, scopes):
        self.calls.append((profile, reference, scopes))
        return AccessCredential(
            "unit-test-secret-value", "model", scopes,
            datetime.now(timezone.utc) + timedelta(minutes=5),
        )

    def clear(self, reason):
        self.clears.append(reason)


def _read_channel(path: Path) -> dict[str, str]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(path))
    client.sendall(b'{"pane":"%1"}')
    chunks = []
    while True:
        value = client.recv(65536)
        if not value:
            break
        chunks.append(value)
    client.close()
    return json.loads(b"".join(chunks))


def test_refs_resolved_via_broker_and_channel_is_not_a_secret_file(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    broker = Broker()
    injector = PaneCredentialInjector()
    channel = injector.prepare(
        {"ANTHROPIC_API_KEY": "vault://model/current"}, broker=broker, run_dir=tmp_path,
    )
    try:
        assert broker.calls
        assert channel.socket_path.exists()
        assert not channel.socket_path.is_file()
        assert _read_channel(channel.socket_path)["ANTHROPIC_API_KEY"] == "unit-test-secret-value"
        for artifact in tmp_path.rglob("*"):
            if artifact.is_file():
                assert "unit-test-secret-value" not in artifact.read_text(encoding="utf-8")
    finally:
        injector.destroy(channel)


def test_destroy_is_idempotent_and_clears_broker(tmp_path: Path) -> None:
    broker = Broker()
    injector = PaneCredentialInjector()
    channel = injector.prepare(
        {"ANTHROPIC_API_KEY": "vault://model/current"}, broker=broker, run_dir=tmp_path,
    )

    injector.destroy(channel)
    injector.destroy(channel)

    assert not channel.socket_path.exists()
    assert broker.clears == ["team-stopped"]


def test_launcher_chdirs_into_worktree_and_sets_local_git_identity_only_when_present(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    broker = Broker()
    injector = PaneCredentialInjector(executables={"opencode": "/usr/bin/opencode"})
    channel = injector.prepare(
        {"ANTHROPIC_API_KEY": "vault://model/current"}, broker=broker, run_dir=tmp_path,
    )
    try:
        source = (channel.launcher_dir / "opencode").read_text(encoding="utf-8")
        worktree_index = source.index("SKILLIFY_WORKTREE")
        chdir_index = source.index("os.chdir(worktree)")
        git_name_index = source.index('"user.name"')
        execve_index = source.index("os.execve(")
        assert worktree_index < chdir_index < git_name_index < execve_index
        assert "if worktree:" in source
        assert '["git", "config", "--worktree", "user.name", worker_id]' in source
        assert '["git", "config", "--worktree", "user.email"' in source
        assert "@skillify.local.invalid" in source
        # argv passthrough must remain untouched by this change.
        assert "sys.argv[1:]" in source
    finally:
        injector.destroy(channel)


def test_launcher_falls_back_to_tmux_agent_id_when_env_worktree_absent(
    tmp_path: Path, monkeypatch,
) -> None:
    """The upstream CLI adapter only renders SKILLIFY_WORKER_ID/SKILLIFY_WORKTREE
    as a per-agent env prefix for opencode panes, not claude panes (confirmed
    against the real bundle during S10 real-machine testing). Claude-type
    launchers must fall back to resolving identity via the tmux pane's
    @agent_id option and the worktree-registry.json this run_dir carries."""
    monkeypatch.chdir(tmp_path)
    broker = Broker()
    injector = PaneCredentialInjector(executables={"claude-code": "/usr/bin/claude"})
    channel = injector.prepare(
        {"ANTHROPIC_API_KEY": "vault://model/current"}, broker=broker, run_dir=tmp_path,
    )
    try:
        source = (channel.launcher_dir / "claude").read_text(encoding="utf-8")
        assert "tmux" in source
        assert "@agent_id" in source
        assert "TMUX_PANE" in source
        assert "worktree-registry.json" in source
        # Fallback must only run when the primary channel (env var) is absent.
        assert "if not worktree:" in source
    finally:
        injector.destroy(channel)


def test_launcher_source_and_channel_never_contain_the_secret_value(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    broker = Broker()
    injector = PaneCredentialInjector(executables={"opencode": "/usr/bin/opencode"})
    channel = injector.prepare(
        {"ANTHROPIC_API_KEY": "vault://model/current"}, broker=broker, run_dir=tmp_path,
    )
    try:
        source = (channel.launcher_dir / "opencode").read_text(encoding="utf-8")
        assert "unit-test-secret-value" not in source
        assert "SSH_AUTH_SOCK" not in source
        assert "GIT_ASKPASS" not in source
        assert "credential.helper" not in source
        for artifact in tmp_path.rglob("*"):
            if artifact.is_file():
                assert "unit-test-secret-value" not in artifact.read_text(encoding="utf-8")
    finally:
        injector.destroy(channel)


def test_launchers_project_worker_mcp_without_embedding_credentials(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    broker = Broker()
    injector = PaneCredentialInjector(executables={
        "opencode": "/usr/bin/opencode",
        "claude-code": "/usr/bin/claude",
    })
    channel = injector.prepare(
        {"ANTHROPIC_API_KEY": "vault://model/current"}, broker=broker, run_dir=tmp_path,
    )
    try:
        opencode = (channel.launcher_dir / "opencode").read_text(encoding="utf-8")
        claude = (channel.launcher_dir / "claude").read_text(encoding="utf-8")
        assert 'opencode_config["mcp"] = mcp_config["mcp"]' in opencode
        assert '"--mcp-config"' in claude
        assert '"--allowedTools"' in claude
        assert '"acceptEdits"' in claude
        assert "unit-test-secret-value" not in opencode + claude
    finally:
        injector.destroy(channel)
