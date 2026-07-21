from __future__ import annotations

import os
from pathlib import Path

import yaml

from skillify.agent.shogun.config_gen import generate_config


def _bundle(root: Path) -> Path:
    root.mkdir()
    entrypoint = root / "shutsujin_departure.sh"
    entrypoint.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    entrypoint.chmod(0o755)
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "inbox_write.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "settings.yaml").write_text("upstream: true\n", encoding="utf-8")
    (root / "queue").mkdir()
    (root / "queue" / "shared.txt").write_text("must-not-project", encoding="utf-8")
    return root


def _generate(bundle: Path, run_dir: Path):
    return generate_config(
        install_root=bundle,
        run_dir=run_dir,
        preferred_cli="opencode",
        worker_count=2,
        model="test-model",
    )


def test_generated_queue_dir_is_the_dir_upstream_reads(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    run_dir = tmp_path / "run"
    generated = _generate(bundle, run_dir)

    assert generated.queue_dir == run_dir / "queue"
    assert Path(generated.command[0]) == run_dir / "shutsujin_departure.sh"
    assert generated.environment["HOME"] == str(run_dir / "home")
    assert generated.environment["OPENCODE_DISABLE_AUTOUPDATE"] == "1"
    assert os.path.samefile(bundle / "shutsujin_departure.sh", generated.command[0])
    assert not (generated.queue_dir / "shared.txt").exists()


def test_tmux_3_0_compatibility_launcher_only_rewrites_window_size(
    tmp_path: Path, monkeypatch,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    monkeypatch.setattr("skillify.agent.shogun.config_gen.shutil.which", lambda _: "/usr/bin/tmux")
    generated = _generate(bundle, tmp_path / "run")
    launcher = tmp_path / "run" / ".skillify-bin" / "tmux"

    assert launcher.exists()
    assert "window-size largest" in launcher.read_text(encoding="utf-8")
    assert generated.environment["PATH"].split(os.pathsep)[0] == str(launcher.parent)


def test_two_teams_get_disjoint_queue_dirs(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    first = _generate(bundle, tmp_path / "run-a")
    second = _generate(bundle, tmp_path / "run-b")

    assert first.queue_dir != second.queue_dir
    assert bundle not in first.queue_dir.parents
    assert bundle not in second.queue_dir.parents
    assert first.queue_dir.parent != second.queue_dir.parent


def test_preferred_cli_applies_to_every_agent_including_shogun(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    generated = _generate(bundle, tmp_path / "run")

    settings = yaml.safe_load(generated.settings_path.read_text(encoding="utf-8"))
    agents = settings["cli"]["agents"]
    assert set(agents) == {"shogun", "karo", "ashigaru1", "ashigaru2", "gunshi"}
    assert {agent["type"] for agent in agents.values()} == {"opencode"}


def test_claude_home_seeds_only_non_secret_first_run_state(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    generated = generate_config(
        install_root=bundle,
        run_dir=tmp_path / "run",
        preferred_cli="claude-code",
        worker_count=1,
        model="test-model",
        credential_refs={"ANTHROPIC_AUTH_TOKEN": "local://model"},
    )

    state = yaml.safe_load(
        (tmp_path / "run" / "home" / ".claude.json").read_text(encoding="utf-8")
    )
    assert state == {
        "hasCompletedOnboarding": True,
        "theme": "dark",
        "projects": {
            str((tmp_path / "run").resolve()): {"hasTrustDialogAccepted": True},
        },
    }
    assert generated.environment["HOME"] == str(tmp_path / "run" / "home")
    assert generated.environment["DISABLE_AUTOUPDATER"] == "1"


def test_worker_worktrees_add_env_only_to_matching_ashigaru_agents(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    worktree1 = tmp_path / "wt1"
    generated = generate_config(
        install_root=bundle,
        run_dir=tmp_path / "run",
        preferred_cli="opencode",
        worker_count=2,
        model="test-model",
        worker_worktrees={"ashigaru1": worktree1},
    )

    settings = yaml.safe_load(generated.settings_path.read_text(encoding="utf-8"))
    agents = settings["cli"]["agents"]
    assert agents["ashigaru1"]["env"] == {
        "SKILLIFY_WORKER_ID": "ashigaru1",
        "SKILLIFY_WORKTREE": str(worktree1),
    }
    assert "env" not in agents["ashigaru2"]
    assert "env" not in agents["shogun"]
    assert "env" not in agents["karo"]
    assert "env" not in agents["gunshi"]


def test_worker_worktrees_omitted_is_byte_identical_to_before(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    without_param = _generate(bundle, tmp_path / "run-without")
    with_none = generate_config(
        install_root=bundle,
        run_dir=tmp_path / "run-with-none",
        preferred_cli="opencode",
        worker_count=2,
        model="test-model",
        worker_worktrees=None,
    )

    text_without = without_param.settings_path.read_text(encoding="utf-8")
    text_with_none = with_none.settings_path.read_text(encoding="utf-8")
    assert text_without == text_with_none
    settings = yaml.safe_load(text_without)
    for agent in settings["cli"]["agents"].values():
        assert "env" not in agent
