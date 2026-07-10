"""T1.5 — full `install_skill()` install of a skill with real `dependencies.python`,
served from a hand-rolled local PEP 503 "simple" index (standing in for devpi, which isn't
reachable in this sandbox — see infra/README.md). Exercises the exact `--index-url` codepath
`skillctl install` uses in production against a real devpi.

Known gap (flagging per the joint-review ask): in this Windows sandbox, the `uv` subprocess
cannot reach a same-machine `http.server` on 127.0.0.1 — it hangs for ~130s and times out,
even though Python's own `requests` calls to equivalent local servers work fine everywhere
else in this suite (fake_forgejo, static_file_server). That points at a sandbox-specific
restriction on outbound connections from the `uv.exe` subprocess specifically, not a bug in
`skillify.install.venv`/`installer` — the `--index-url` argument is a one-line difference from
the `--find-links` codepath that IS verified end-to-end with a real `uv venv` + `uv pip
install` + import in test_venv_offline.py. Skipped here rather than left flaky; unskip and
run on a host without this restriction (e.g. Linux CI, or outside this sandbox) to close the
gap for real.
"""

from __future__ import annotations

import http.server
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

from skillify.common.config import SkillifyConfig
from skillify.install.installer import install_skill
from skillify.install.venv import venv_python_path

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skip(
        reason="uv subprocess cannot reach 127.0.0.1 in this sandbox (see module docstring); "
        "mechanism is verified via test_venv_offline.py's --find-links path instead"
    ),
]


def _build_pep503_index(index_root: Path) -> None:
    pkg_dir = index_root / "simple" / "demo-pkg"
    pkg_dir.mkdir(parents=True)
    wheel_path = pkg_dir / "demo_pkg-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("demo_pkg/__init__.py", "MARKER = 'installed-via-index-url'\n")
        zf.writestr("demo_pkg-0.1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: demo-pkg\nVersion: 0.1.0\n")
        zf.writestr(
            "demo_pkg-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: skillify-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        zf.writestr("demo_pkg-0.1.0.dist-info/RECORD", "")
    (pkg_dir / "index.html").write_text(
        '<!DOCTYPE html><html><body>'
        f'<a href="{wheel_path.name}">{wheel_path.name}</a>'
        "</body></html>",
        encoding="utf-8",
    )


@pytest.fixture()
def pep503_index(tmp_path: Path):
    index_root = tmp_path / "index"
    _build_pep503_index(index_root)
    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(index_root), **kw)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/simple/"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_install_skill_installs_real_python_deps_via_index_url(
    tmp_path: Path, pep503_index: str
) -> None:
    from tests.test_installer import _make_skill  # reuse the SKILL.md/skill.yaml fixture helper

    skill_dir = _make_skill(tmp_path)
    manifest_path = skill_dir / "skill.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8") + "\ndependencies:\n  python: ['demo-pkg']\n",
        encoding="utf-8",
    )
    (skill_dir / "requirements.txt").write_text("demo-pkg\n", encoding="utf-8")

    static_dir = tmp_path / "static"
    from skillify.packaging.pack import pack_skill

    result = pack_skill(skill_dir, static_dir)

    import http.server as _hs

    handler = lambda *a, **kw: _hs.SimpleHTTPRequestHandler(*a, directory=str(static_dir), **kw)
    artifact_server = _hs.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=artifact_server.serve_forever, daemon=True)
    thread.start()
    try:
        cfg = SkillifyConfig(home=tmp_path / "home", devpi_index_url=pep503_index)
        url = f"http://127.0.0.1:{artifact_server.server_port}/{result.tarball_path.name}"
        lock = install_skill("excel/pivot-analysis@0.1.0", cfg=cfg, source_override=url)
    finally:
        artifact_server.shutdown()
        thread.join(timeout=2)

    assert lock.venvPath is not None
    python_path = venv_python_path(Path(lock.venvPath))
    proc = subprocess.run(
        [str(python_path), "-c", "import demo_pkg; print(demo_pkg.MARKER)"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "installed-via-index-url" in proc.stdout
