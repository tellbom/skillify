"""T1.5 — real (offline) verification that python deps actually land in the per-skill venv.

Builds a tiny hand-crafted wheel and installs it via `uv pip install --find-links ... --no-index`,
so this exercises the real `uv venv` + `uv pip install` codepath without needing network access
to PyPI or a live devpi (T0.3's devpi service isn't reachable in this sandbox — see infra/README.md).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from skillify.install.venv import ensure_venv, install_python_deps, venv_python_path

pytestmark = pytest.mark.slow


def _build_demo_wheel(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = dest_dir / "demo_pkg-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("demo_pkg/__init__.py", "MARKER = 'installed-from-offline-wheel'\n")
        zf.writestr(
            "demo_pkg-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: demo-pkg\nVersion: 0.1.0\n",
        )
        zf.writestr(
            "demo_pkg-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: skillify-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr("demo_pkg-0.1.0.dist-info/RECORD", "")
    return wheel_path


def test_ensure_venv_and_install_offline_wheel(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheels"
    _build_demo_wheel(wheel_dir)

    venv_dir = tmp_path / "venvs" / "excel__pivot-analysis"
    python_path = ensure_venv(venv_dir)
    assert python_path.is_file()

    install_python_deps(
        venv_dir, ["demo-pkg"], index_url=None, extra_args=["--find-links", str(wheel_dir), "--no-index"]
    )

    import subprocess

    result = subprocess.run(
        [str(python_path), "-c", "import demo_pkg; print(demo_pkg.MARKER)"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "installed-from-offline-wheel" in result.stdout


def test_ensure_venv_is_idempotent(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venvs" / "excel__lookup"
    p1 = ensure_venv(venv_dir)
    p2 = ensure_venv(venv_dir)
    assert p1 == p2 == venv_python_path(venv_dir)
