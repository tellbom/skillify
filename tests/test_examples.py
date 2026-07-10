"""T1.6 — full publish -> install -> run loop for the hand-written example skills.

For `text/word-frequency`'s real PyPI dependency (`tabulate`), this test substitutes a local
offline wheel of the same name/API surface via `--find-links` (see test_venv_offline.py /
test_installer_python_deps.py for why: no outbound network from the `uv` subprocess works in
this sandbox). The example's own `skill.yaml`/`requirements.txt` still declare the real
`tabulate` PyPI package for production use against a real devpi mirror.
"""

from __future__ import annotations

import http.server
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

from skillify.cli.publish_cmd import run_publish
from skillify.common.config import SkillifyConfig
from skillify.install.installer import install_skill
from skillify.install.venv import venv_python_path
from tests.fake_forgejo import fake_forgejo  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


class _Console:
    def print(self, *a, **k):
        pass


def _publish(tmp_path: Path, fake_forgejo, monkeypatch, skill_dir: Path) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "publish-home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())


def test_pivot_analysis_full_loop_publish_install(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    skill_dir = EXAMPLES_DIR / "excel" / "pivot-analysis"
    _publish(tmp_path, fake_forgejo, monkeypatch, skill_dir)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    lock = install_skill("excel/pivot-analysis", cfg=cfg)
    assert lock.version == "0.1.0"
    installed_skill_md = cfg.skills_dir / "excel" / "pivot-analysis" / "SKILL.md"
    assert installed_skill_md.is_file()
    assert "pivot" in installed_skill_md.read_text(encoding="utf-8").lower()


def _build_offline_tabulate_wheel(dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = dest_dir / "tabulate-0.9.0-py3-none-any.whl"
    # Minimal reimplementation covering only what scripts/word_frequency.py calls:
    # tabulate(rows, headers=[...]) -> str
    tabulate_py = (
        "def tabulate(rows, headers=None):\n"
        "    headers = headers or []\n"
        "    lines = ['\\t'.join(str(h) for h in headers)] if headers else []\n"
        "    for row in rows:\n"
        "        lines.append('\\t'.join(str(c) for c in row))\n"
        "    return '\\n'.join(lines)\n"
    )
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("tabulate.py", tabulate_py)
        zf.writestr("tabulate-0.9.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: tabulate\nVersion: 0.9.0\n")
        zf.writestr(
            "tabulate-0.9.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: skillify-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr("tabulate-0.9.0.dist-info/RECORD", "")


def test_word_frequency_full_loop_publish_install_and_run(
    tmp_path: Path, fake_forgejo, monkeypatch
) -> None:
    skill_dir = EXAMPLES_DIR / "text" / "word-frequency"
    _publish(tmp_path, fake_forgejo, monkeypatch, skill_dir)

    # Redirect the venv's dependency source to an offline wheel dir instead of a real devpi.
    wheel_dir = tmp_path / "offline-wheels"
    _build_offline_tabulate_wheel(wheel_dir)
    real_install_python_deps = __import__(
        "skillify.install.venv", fromlist=["install_python_deps"]
    ).install_python_deps

    def _patched_install_python_deps(venv_dir, requirements, *, index_url):
        return real_install_python_deps(
            venv_dir, requirements, index_url=None, extra_args=["--find-links", str(wheel_dir), "--no-index"]
        )

    monkeypatch.setattr("skillify.install.installer.install_python_deps", _patched_install_python_deps)

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}", forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    lock = install_skill("text/word-frequency", cfg=cfg)

    assert lock.pythonDeps == ["tabulate>=0.9"]
    assert lock.venvPath is not None

    installed_script = cfg.skills_dir / "text" / "word-frequency" / "scripts" / "word_frequency.py"
    assert installed_script.is_file()

    sample_text = tmp_path / "sample.txt"
    sample_text.write_text("the quick brown fox jumps over the lazy dog\nthe dog barks at the fox\n", encoding="utf-8")

    python_path = venv_python_path(Path(lock.venvPath))
    proc = subprocess.run(
        [str(python_path), str(installed_script), str(sample_text), "--top", "3"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "the" in proc.stdout
    assert "4" in proc.stdout  # "the" appears 4 times in the sample text
