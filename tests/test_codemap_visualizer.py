from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from skillify.cli.bridge_cmd import LocalOutbox
from skillify.codemap.task_runner import CodemapTaskRunner
from skillify.codemap.visualizer import (
    CodemapError,
    CodemapStatus,
    GitNexusVisualizer,
    load_manifest,
    resolve_workspace_alias,
    verify_source_archive,
)
from skillify.tasks.protocol import TaskEnvelope


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)


def test_manifest_pins_noncommercial_gitnexus_without_trial_expiry(tmp_path: Path) -> None:
    manifest = load_manifest(ROOT / "infra/offline/gitnexus-visualizer-manifest.json")
    assert manifest.version == "1.6.9"
    assert manifest.use_policy == "personal-noncommercial-only"
    assert manifest.license_expires_at is None
    archive = tmp_path / "source.tar.gz"
    archive.write_bytes(b"wrong")
    with pytest.raises(CodemapError, match="checksum"):
        verify_source_archive(archive, manifest)


def test_workspace_alias_never_accepts_a_path(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    assert resolve_workspace_alias("repo", {"repo": str(workspace)}) == workspace.resolve()
    with pytest.raises(CodemapError, match="alias"):
        resolve_workspace_alias("../repo", {"../repo": str(workspace)})


def test_start_indexes_an_isolated_snapshot_and_binds_localhost(monkeypatch, tmp_path: Path) -> None:
    manifest = load_manifest(ROOT / "infra/offline/gitnexus-visualizer-manifest.json")
    runtime = tmp_path / "runtime"
    entrypoint = runtime / manifest.entrypoint
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("// pinned GitNexus", encoding="utf-8")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('hello')\n", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "v22.23.1\n", "")
        snapshot = Path(command[3])
        (snapshot / ".gitnexus").mkdir()
        return subprocess.CompletedProcess(command, 0, "indexed", "")

    class Process:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr("skillify.codemap.visualizer.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    visualizer = GitNexusVisualizer(
        manifest=manifest, runtime_root=runtime, state_root=tmp_path / "state",
        run=fake_run, popen=lambda *args, **kwargs: Process(),
        connect=lambda address, timeout: SimpleNamespace(close=lambda: None),
    )
    status = visualizer.start("repo", workspace, port=4747)

    assert status.state == "ready" and status.pid == 4242
    assert not (workspace / ".gitnexus").exists()
    assert (tmp_path / "state/repo/workspace/.gitnexus").is_dir()
    analyze = next(command for command in commands if "analyze" in command)
    assert "--index-only" in analyze and "--skip-git" in analyze
    state = json.loads((tmp_path / "state/repo/runtime.json").read_text(encoding="utf-8"))
    assert state["port"] == 4747


def test_start_reports_failure_when_process_exits_before_binding(monkeypatch, tmp_path: Path) -> None:
    manifest = load_manifest(ROOT / "infra/offline/gitnexus-visualizer-manifest.json")
    runtime = tmp_path / "runtime"
    entrypoint = runtime / manifest.entrypoint
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("// pinned GitNexus", encoding="utf-8")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    def fake_run(command, **kwargs):
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "v22.23.1\n", "")
        (Path(command[3]) / ".gitnexus").mkdir()
        return subprocess.CompletedProcess(command, 0, "indexed", "")

    class Process:
        pid = 4242

        def poll(self):
            return 1

    monkeypatch.setattr(
        "skillify.codemap.visualizer.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    visualizer = GitNexusVisualizer(
        manifest=manifest, runtime_root=runtime, state_root=tmp_path / "state",
        run=fake_run, popen=lambda *args, **kwargs: Process(),
        connect=lambda address, timeout: (_ for _ in ()).throw(ConnectionRefusedError()),
    )
    status = visualizer.start("repo", workspace)

    assert status.state == "failed"
    assert "exited before binding" in status.detail
    with pytest.raises(CodemapError, match="started before opening"):
        visualizer.open("repo")


def test_start_persists_scan_failure_detail(monkeypatch, tmp_path: Path) -> None:
    manifest = load_manifest(ROOT / "infra/offline/gitnexus-visualizer-manifest.json")
    runtime = tmp_path / "runtime"
    entrypoint = runtime / manifest.entrypoint
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("// pinned GitNexus", encoding="utf-8")
    workspace = tmp_path / "repo"; workspace.mkdir()

    def fake_run(command, **kwargs):
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "v22.23.1\n", "")
        raise subprocess.CalledProcessError(
            1, command, stderr="native dependency unavailable\nlibssl.so.3 is missing\n",
        )

    monkeypatch.setattr("skillify.codemap.visualizer.shutil.which", lambda _: "/usr/bin/node")
    visualizer = GitNexusVisualizer(
        manifest=manifest, runtime_root=runtime, state_root=tmp_path / "state", run=fake_run,
    )

    status = visualizer.start("repo", workspace)

    assert status.state == "failed"
    assert "libssl.so.3 is missing" in status.detail
    persisted = json.loads((tmp_path / "state/repo/runtime.json").read_text(encoding="utf-8"))
    assert persisted["state"] == "failed" and "libssl.so.3" in persisted["detail"]


def test_start_times_out_without_reporting_ready(monkeypatch, tmp_path: Path) -> None:
    manifest = load_manifest(ROOT / "infra/offline/gitnexus-visualizer-manifest.json")
    runtime = tmp_path / "runtime"
    entrypoint = runtime / manifest.entrypoint
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("// pinned GitNexus", encoding="utf-8")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    clock = iter((0.0, 0.0, 1.0))

    def fake_run(command, **kwargs):
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, "v22.23.1\n", "")
        (Path(command[3]) / ".gitnexus").mkdir()
        return subprocess.CompletedProcess(command, 0, "indexed", "")

    class Process:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(
        "skillify.codemap.visualizer.shutil.which",
        lambda name: "/usr/bin/node" if name == "node" else None,
    )
    terminated: list[int] = []
    monkeypatch.setattr(
        "skillify.codemap.visualizer.GitNexusVisualizer._terminate_process",
        lambda self, pid: terminated.append(pid),
    )
    visualizer = GitNexusVisualizer(
        manifest=manifest, runtime_root=runtime, state_root=tmp_path / "state",
        run=fake_run, popen=lambda *args, **kwargs: Process(),
        connect=lambda address, timeout: (_ for _ in ()).throw(ConnectionRefusedError()),
        monotonic=lambda: next(clock), sleep=lambda seconds: None, readiness_timeout=1.0,
    )
    status = visualizer.start("repo", workspace)

    assert status.state == "failed"
    assert "timed out" in status.detail
    assert terminated == [4242]


def test_codemap_task_runner_emits_allowlisted_lifecycle(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()

    class Visualizer:
        manifest = SimpleNamespace(version="1.6.9")

        def start(self, alias, resolved_workspace):
            assert alias == "repo" and resolved_workspace == workspace
            return CodemapStatus(alias, "ready", detail="GitNexus is ready")

    envelope = TaskEnvelope(
        task_id="codemap-1", endpoint_id="endpoint-1",
        workflow_id="codemap.visualization.start", workflow_version="1.0.0",
        workspace_alias="repo", parameters={}, issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5), nonce="nonce-1", runtime="codemap",
        state_version=1,
    ).sign(b"secret")
    outbox = LocalOutbox(tmp_path / "outbox.jsonl")
    runner = CodemapTaskRunner(Visualizer(), lambda alias: workspace, outbox, clock=lambda: NOW)

    assert runner.run(envelope, state_version=2) == 7
    payloads = [record["payload"] for record in outbox.pending()]
    assert [item["eventType"] for item in payloads] == [
        "codemap.visualization.requested", "codemap.visualization.scan_started",
        "codemap.visualization.scan_completed", "codemap.visualization.started",
        "codemap.visualization.ready",
    ]
    assert [item["stateVersion"] for item in payloads] == [2, 3, 4, 5, 6]
    serialized = json.dumps(payloads).casefold()
    assert str(workspace).casefold() not in serialized
