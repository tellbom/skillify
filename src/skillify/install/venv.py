"""Per-skill venv creation + dependency install via `uv` (T1.4 core / T1.5 python deps)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


class UvNotFound(Exception):
    def __init__(self) -> None:
        super().__init__("`uv` not found on PATH — required to create per-skill venvs (see `skillctl doctor`)")


class VenvError(Exception):
    pass


def venv_python_path(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def ensure_venv(venv_dir: Path) -> Path:
    """Create `venv_dir` via `uv venv` if it doesn't already exist. Returns the venv's python path."""
    if shutil.which("uv") is None:
        raise UvNotFound()
    python_path = venv_python_path(venv_dir)
    if python_path.is_file():
        return python_path
    proc = subprocess.run(
        ["uv", "venv", str(venv_dir)], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise VenvError(f"`uv venv {venv_dir}` failed:\n{proc.stderr}")
    return python_path


def install_python_deps(
    venv_dir: Path, requirements: list[str], *, index_url: str | None, extra_args: list[str] | None = None
) -> None:
    if not requirements:
        return
    if shutil.which("uv") is None:
        raise UvNotFound()
    python_path = venv_python_path(venv_dir)
    cmd = ["uv", "pip", "install", "--python", str(python_path), *requirements]
    if index_url:
        cmd += ["--index-url", index_url]
    if extra_args:
        cmd += extra_args
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise VenvError(f"`{' '.join(cmd)}` failed:\n{proc.stderr}")
