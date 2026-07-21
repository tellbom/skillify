"""Tests for the P1-4 per-task Docker index orchestrator (source :ro, index writable, no egress)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from skillify.codemap.index_orchestrator import IndexError, IndexOrchestrator


def _orchestrator(tmp_path: Path, run) -> IndexOrchestrator:
    return IndexOrchestrator(
        tasks_root=tmp_path / "tasks",
        image="skillify/gitnexus:1.6.9",
        network="skillify-gitnexus-offline",
        run=run,
    )


def _seed_source(tmp_path: Path, task_id: str) -> None:
    source = tmp_path / "tasks" / task_id / "source"
    source.mkdir(parents=True)
    (source / "main.py").write_text("print(1)\n", encoding="utf-8")


def test_index_raises_if_source_dir_missing(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, run=lambda *a, **k: pytest.fail("should not run docker"))

    with pytest.raises(IndexError, match="source"):
        orchestrator.index("task-1")


def test_index_rejects_invalid_task_id(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, run=lambda *a, **k: pytest.fail("should not run docker"))

    with pytest.raises(IndexError):
        orchestrator.index("../escape")


def test_index_builds_expected_docker_command(tmp_path: Path) -> None:
    _seed_source(tmp_path, "task-1")
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        (tmp_path / "tasks" / "task-1" / "index" / "manifest.json").write_text("{}\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "indexed", "")

    orchestrator = _orchestrator(tmp_path, run=fake_run)
    result = orchestrator.index("task-1")

    command = captured["command"]
    assert command[:3] == ["docker", "run", "--rm"]
    assert "--network" in command and command[command.index("--network") + 1] == "skillify-gitnexus-offline"
    source_dir = tmp_path / "tasks" / "task-1" / "source"
    index_dir = tmp_path / "tasks" / "task-1" / "index"
    assert f"{source_dir}:/workspace:ro" in command
    assert f"{index_dir}:/workspace/.gitnexus" in command
    assert command[-1] == "--no-stats"
    assert "analyze" in command
    assert result.source_dir == source_dir
    assert result.index_dir == index_dir


def test_index_raises_on_nonzero_exit_with_stderr_detail(tmp_path: Path) -> None:
    _seed_source(tmp_path, "task-1")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "boom: disk full")

    orchestrator = _orchestrator(tmp_path, run=fake_run)

    with pytest.raises(IndexError, match="boom: disk full"):
        orchestrator.index("task-1")


def test_index_raises_if_index_dir_ends_up_empty(tmp_path: Path) -> None:
    _seed_source(tmp_path, "task-1")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "")  # no files written to index/

    orchestrator = _orchestrator(tmp_path, run=fake_run)

    with pytest.raises(IndexError, match="did not produce"):
        orchestrator.index("task-1")
