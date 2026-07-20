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
