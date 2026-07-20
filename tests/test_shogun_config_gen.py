from __future__ import annotations

import os
from pathlib import Path

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
    assert os.path.samefile(bundle / "shutsujin_departure.sh", generated.command[0])
    assert not (generated.queue_dir / "shared.txt").exists()


def test_two_teams_get_disjoint_queue_dirs(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path / "bundle")
    first = _generate(bundle, tmp_path / "run-a")
    second = _generate(bundle, tmp_path / "run-b")

    assert first.queue_dir != second.queue_dir
    assert bundle not in first.queue_dir.parents
    assert bundle not in second.queue_dir.parents
    assert first.queue_dir.parent != second.queue_dir.parent
