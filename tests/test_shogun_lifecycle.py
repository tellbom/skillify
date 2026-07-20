from __future__ import annotations

from pathlib import Path
import os
import signal

from skillify.agent.shogun.config_gen import GeneratedShogunConfig
from skillify.agent.shogun.fake_runtime import FakeRuntime
from skillify.agent.shogun.lifecycle import ShogunLifecycle, TeamHandle


def _generated(run_dir: Path) -> GeneratedShogunConfig:
    queue = run_dir / "queue"
    queue.mkdir(parents=True)
    return GeneratedShogunConfig(
        run_dir / "config/settings.yaml", run_dir / "config/permissions.yaml",
        queue, (str(run_dir / "shutsujin_departure.sh"),), {},
    )


def test_start_returns_team_handle_not_starter_pid(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    lifecycle = ShogunLifecycle(runtime, tmp_path / "active-team.lock")
    generated = _generated(tmp_path / "run")

    team = lifecycle.start("task-1", generated, install_root=tmp_path / "unused")

    assert isinstance(team.handle, TeamHandle)
    assert team.handle.session
    assert not hasattr(team, "pid")
    assert runtime.is_alive(team.handle)


def test_cancel_targets_session_and_supervisor(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    guard = tmp_path / "active-team.lock"
    lifecycle = ShogunLifecycle(runtime, guard)
    team = lifecycle.start("task-1", _generated(tmp_path / "run"), install_root=tmp_path)

    lifecycle.cancel(team)

    assert ("kill-session", team.handle.session) in runtime.actions
    assert ("pkill", "watcher_supervisor.sh") in runtime.actions
    assert not runtime.is_alive(team.handle)
    assert not guard.exists()
    assert not team.run_dir.exists()


def test_handle_roundtrips_for_recovery(tmp_path: Path) -> None:
    original = TeamHandle("shogun", (tmp_path / "run").resolve())
    path = tmp_path / "team-handle.json"
    original.write(path)

    assert TeamHandle.read(path) == original


def test_real_runtime_supplies_noninteractive_terminal_defaults(monkeypatch) -> None:
    from skillify.agent.shogun.lifecycle import ProcessRuntime

    monkeypatch.delenv("TERM", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    runtime = ProcessRuntime()
    environment = runtime.process_environment({"HOME": "/task/home"})

    assert environment["TERM"] == "xterm-256color"
    assert environment["LANG"] == "C.UTF-8"
    assert environment["HOME"] == "/task/home"
    assert "DEEPSEEK_API_KEY" not in environment


def test_cleanup_terminates_processes_still_rooted_in_run_dir(
    tmp_path: Path, monkeypatch,
) -> None:
    from skillify.agent.shogun.lifecycle import ProcessRuntime

    runtime = ProcessRuntime()
    observations = iter(({101, 102}, set()))
    monkeypatch.setattr(runtime, "_processes_in_run_dir", lambda _: next(observations, set()))
    killed = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    runtime._terminate_run_dir_processes(tmp_path / "run")

    assert set(killed) == {(101, signal.SIGTERM), (102, signal.SIGTERM)}
