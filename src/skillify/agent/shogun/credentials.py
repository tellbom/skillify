"""Short-lived credential delivery to Shogun-created CLI panes."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from skillify.credentials.identities import AccessCredential


_ENV = re.compile(r"^[A-Z][A-Z0-9_]*$")
_REF = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s]+$")


class CredentialBrokerLike(Protocol):
    def credential(
        self, auth_profile: str, credential_ref: str, approved_scopes: frozenset[str],
    ) -> AccessCredential: ...

    def clear(self, reason: str) -> None: ...


@dataclass(frozen=True)
class InjectionChannel:
    socket_path: Path
    launcher_dir: Path


@dataclass
class _ChannelState:
    channel: InjectionChannel
    refs: dict[str, str]
    broker: CredentialBrokerLike
    server: socket.socket
    stop: threading.Event
    thread: threading.Thread


class PaneCredentialInjector:
    """Serve credentials from memory to fixed CLI launchers over a local socket."""

    def __init__(
        self,
        *,
        bindings: Mapping[str, tuple[str, frozenset[str]]] | None = None,
        executables: Mapping[str, str] | None = None,
    ) -> None:
        self.bindings = dict(bindings or {})
        self.executables = dict(executables or {})
        self._states: dict[Path, _ChannelState] = {}

    def _binding(
        self, env_name: str, credential_ref: str, broker: CredentialBrokerLike,
    ) -> tuple[str, frozenset[str]]:
        configured = self.bindings.get(env_name)
        if configured is not None:
            return configured
        profiles = getattr(broker, "profiles", {})
        matches = [
            profile for profile in profiles.values()
            if getattr(profile, "credential_ref", None) == credential_ref
        ]
        if len(matches) == 1:
            profile = matches[0]
            return str(profile.name), frozenset(profile.scopes)
        # A deliberately deterministic fallback keeps fake brokers simple. A
        # production CredentialBroker will reject it unless explicitly bound.
        return env_name.lower().replace("_", "-"), frozenset()

    def _resolve(
        self, state: _ChannelState,
    ) -> dict[str, str]:
        values: dict[str, str] = {}
        for env_name, credential_ref in state.refs.items():
            profile, scopes = self._binding(env_name, credential_ref, state.broker)
            values[env_name] = state.broker.credential(profile, credential_ref, scopes).value
        return values

    def _serve(self, state: _ChannelState) -> None:
        while not state.stop.is_set():
            try:
                connection, _ = state.server.accept()
            except (OSError, TimeoutError):
                continue
            with connection:
                try:
                    request = json.loads(connection.recv(4096))
                    if not isinstance(request, dict) or not re.fullmatch(
                        r"%[0-9]+", str(request.get("pane", "")),
                    ):
                        continue
                    if hasattr(socket, "SO_PEERCRED"):
                        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                        pid, uid, _ = struct.unpack("3i", raw)
                        if uid != os.getuid():
                            continue
                        try:
                            peer_cwd = Path(f"/proc/{pid}/cwd").resolve(strict=True)
                        except OSError:
                            continue
                        if peer_cwd != state.channel.launcher_dir.parent:
                            continue
                    payload = json.dumps(self._resolve(state), separators=(",", ":")).encode()
                    connection.sendall(payload)
                except (OSError, PermissionError, ValueError):
                    # The caller receives an empty response and fails closed.
                    pass

    def _write_launcher(self, path: Path, executable: str, socket_path: Path) -> None:
        source = f'''#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect({str(socket_path)!r})
sock.sendall(json.dumps({{"pane": os.environ.get("TMUX_PANE", "")}}).encode())
data = bytearray()
while True:
    chunk = sock.recv(65536)
    if not chunk:
        break
    data.extend(chunk)
sock.close()
if not data:
    raise SystemExit("credential broker did not provide a credential")
environment = os.environ.copy()
environment.update(json.loads(data.decode()))
worktree = os.environ.get("SKILLIFY_WORKTREE")
worker_id = os.environ.get("SKILLIFY_WORKER_ID")
if not worktree:
    # Fallback identity channel: the upstream CLI adapter only renders the
    # per-agent env prefix (SKILLIFY_WORKER_ID/SKILLIFY_WORKTREE) for
    # opencode panes, not claude panes. For claude-type panes, resolve
    # identity via the tmux pane's @agent_id option (set by the upstream
    # entrypoint for every pane regardless of CLI type) and look up that
    # worker's worktree in the registry this run_dir carries.
    tmux_pane = os.environ.get("TMUX_PANE", "")
    candidate_worker_id = ""
    if tmux_pane:
        result = subprocess.run(
            ["tmux", "show-options", "-p", "-t", tmux_pane, "-v", "@agent_id"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            candidate_worker_id = result.stdout.strip()
    if candidate_worker_id:
        registry_path = Path(__file__).resolve().parent.parent / "worktree-registry.json"
        if registry_path.exists():
            try:
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                registry = {{}}
            for worker in registry.get("workers", []):
                if worker.get("worker_id") == candidate_worker_id:
                    worktree = worker.get("worktree")
                    worker_id = candidate_worker_id
                    break
if worktree:
    os.chdir(worktree)
    worker_id = worker_id or ""
    # --worktree (not --local): with extensions.worktreeConfig enabled by
    # WorktreeManager.create(), this isolates identity per worktree. --local
    # would write to the single config file every worktree of this repo
    # shares, causing worker identities to collide under concurrent panes.
    subprocess.run(["git", "config", "--worktree", "user.name", worker_id], check=True)
    subprocess.run(
        ["git", "config", "--worktree", "user.email", f"{{worker_id}}@skillify.local.invalid"],
        check=True,
    )
os.execve({executable!r}, [{executable!r}, *sys.argv[1:]], environment)
'''
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700)

    def prepare(
        self,
        refs: Mapping[str, str],
        *,
        broker: CredentialBrokerLike,
        run_dir: Path,
    ) -> InjectionChannel:
        normalized = dict(refs)
        if not normalized or any(
            not _ENV.fullmatch(name) or not _REF.fullmatch(value)
            for name, value in normalized.items()
        ):
            raise ValueError("pane credentials must be non-empty named references")
        root = Path(run_dir).resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        launcher_dir = root / ".skillify-bin"
        launcher_dir.mkdir(mode=0o700, exist_ok=True)
        socket_path = root / ".skillify-credentials.sock"
        socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(socket_path))
        socket_path.chmod(0o600)
        server.listen(16)
        server.settimeout(0.2)
        channel = InjectionChannel(socket_path, launcher_dir)
        placeholder = threading.Thread()
        state = _ChannelState(
            channel, normalized, broker, server, threading.Event(), placeholder,
        )
        try:
            # Resolve once before the team starts so profile/scope failures do not
            # leave a partially launched tmux team. The value is not retained here.
            self._resolve(state)
            names = {"opencode": "opencode", "claude-code": "claude"}
            for source_name, launcher_name in names.items():
                executable = self.executables.get(source_name) or shutil.which(launcher_name)
                if executable:
                    self._write_launcher(launcher_dir / launcher_name, executable, socket_path)
            thread = threading.Thread(
                target=self._serve, args=(state,), name="shogun-credential-channel", daemon=True,
            )
            state.thread = thread
            self._states[socket_path] = state
            thread.start()
            return channel
        except Exception:
            server.close()
            socket_path.unlink(missing_ok=True)
            shutil.rmtree(launcher_dir, ignore_errors=True)
            raise

    def destroy(self, channel: InjectionChannel) -> None:
        state = self._states.pop(channel.socket_path, None)
        if state is None:
            channel.socket_path.unlink(missing_ok=True)
            shutil.rmtree(channel.launcher_dir, ignore_errors=True)
            return
        state.stop.set()
        state.server.close()
        state.thread.join(timeout=1)
        channel.socket_path.unlink(missing_ok=True)
        shutil.rmtree(channel.launcher_dir, ignore_errors=True)
        state.broker.clear("team-stopped")
