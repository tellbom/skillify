"""Tests for T1.4 — install closed loop (download, verify, extract, lock)."""

from __future__ import annotations

import http.server
import tarfile
import threading
from pathlib import Path

import pytest

from skillify.common.config import SkillifyConfig
from skillify.install.extract import ChecksumMismatch, UnsafeArchive, safe_extract, verify_checksum
from skillify.install.installer import InstallError, install_skill
from skillify.install.lock import read_lock
from skillify.packaging.pack import pack_skill
from tests.fake_forgejo import fake_forgejo  # noqa: F401
from tests.fixtures import VALID_MANIFEST, VALID_SKILL_MD


def _make_skill(tmp_path: Path, subdir: str = "src") -> Path:
    skill_dir = tmp_path / subdir / "excel" / "pivot-analysis"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")
    return skill_dir


@pytest.fixture()
def static_file_server(tmp_path: Path):
    directory = tmp_path / "static"
    directory.mkdir()

    handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(directory), **kw)
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, directory
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_install_via_source_override(tmp_path: Path, static_file_server) -> None:
    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, static_dir)

    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    lock = install_skill("excel/pivot-analysis@0.1.0", cfg=cfg, source_override=url)

    assert lock.version == "0.1.0"
    assert lock.sha256 == result.sha256
    installed_dir = cfg.skills_dir / "excel" / "pivot-analysis"
    assert (installed_dir / "SKILL.md").is_file()
    assert (installed_dir / "skill.yaml").is_file()

    stored_lock = read_lock(cfg.locks_dir, "excel", "pivot-analysis")
    assert stored_lock is not None
    assert stored_lock.version == "0.1.0"


def test_install_requires_version_with_source_override(tmp_path: Path, static_file_server) -> None:
    server, static_dir = static_file_server
    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/whatever.tar.gz"

    with pytest.raises(InstallError, match="version"):
        install_skill("excel/pivot-analysis", cfg=cfg, source_override=url)


def test_install_detects_checksum_tampering(tmp_path: Path, static_file_server) -> None:
    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, static_dir)
    # Tamper with the published tarball after packaging but before install.
    result.tarball_path.write_bytes(result.tarball_path.read_bytes() + b"\x00extra-byte")

    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    with pytest.raises(InstallError, match="sha256"):
        install_skill("excel/pivot-analysis@0.1.0", cfg=cfg, source_override=url)


def test_install_via_forgejo(tmp_path: Path, fake_forgejo, monkeypatch) -> None:
    from skillify.cli.publish_cmd import run_publish

    class _Console:
        def print(self, *a, **k):
            pass

    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "publish-home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    skill_dir = _make_skill(tmp_path)
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}",
        forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    lock = install_skill("excel/pivot-analysis", cfg=cfg)  # no version -> latest
    assert lock.version == "0.1.0"
    assert (cfg.skills_dir / "excel" / "pivot-analysis" / "SKILL.md").is_file()


def test_install_with_explicit_version_is_unaffected_by_index_yanked_status(
    tmp_path: Path, fake_forgejo, monkeypatch
) -> None:
    """C-1 sanity check for `skillctl install ns/name@version`: the CLI install path resolves
    directly against Forgejo releases (`resolve_release_artifact` -> `get_release_by_tag`),
    never consulting the DM8/SQLite index at all — so a version's `yanked` flag there (which
    only affects `list_latest`/`search`/`leaderboard`) cannot influence which artifact gets
    installed here. No `SKILLIFY_INDEX_DB_URL` is configured for this test at all, which is
    itself part of the proof: if install_skill needed the index, this would fail outright."""
    from skillify.cli.publish_cmd import run_publish

    class _Console:
        def print(self, *a, **k):
            pass

    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "publish-home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    monkeypatch.delenv("SKILLIFY_INDEX_DB_URL", raising=False)

    skill_dir = _make_skill(tmp_path)
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())

    manifest_path = skill_dir / "skill.yaml"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8").replace("0.1.0", "0.2.0"), encoding="utf-8")
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())

    cfg = SkillifyConfig(
        forgejo_url=f"http://127.0.0.1:{fake_forgejo.server_port}",
        forgejo_token="tok",
        home=tmp_path / "install-home",
    )
    # Explicit older version pins to that exact release even though a newer one exists.
    lock = install_skill("excel/pivot-analysis@0.1.0", cfg=cfg)
    assert lock.version == "0.1.0"

    lock2 = install_skill("excel/pivot-analysis@0.2.0", cfg=cfg)
    assert lock2.version == "0.2.0"


def test_reinstall_overwrites_cleanly(tmp_path: Path, static_file_server) -> None:
    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    (skill_dir / "stray.txt").write_text("v1 only\n", encoding="utf-8")
    result = pack_skill(skill_dir, static_dir)
    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"
    install_skill("excel/pivot-analysis@0.1.0", cfg=cfg, source_override=url)
    assert (cfg.skills_dir / "excel" / "pivot-analysis" / "stray.txt").is_file()

    # Repackage without stray.txt (simulating a later version's tree) and reinstall in place.
    (skill_dir / "stray.txt").unlink()
    manifest_path = skill_dir / "skill.yaml"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8").replace("0.1.0", "0.2.0"), encoding="utf-8")
    result2 = pack_skill(skill_dir, static_dir)
    url2 = f"http://127.0.0.1:{server.server_port}/{result2.tarball_path.name}"
    install_skill("excel/pivot-analysis@0.2.0", cfg=cfg, source_override=url2)

    assert not (cfg.skills_dir / "excel" / "pivot-analysis" / "stray.txt").exists()


def test_install_rejects_mislabeled_artifact_wrong_identity(tmp_path: Path, static_file_server) -> None:
    """C1: a Release asset whose own skill.yaml declares a different namespace/name than
    requested must be rejected, even though checksum verification passes (it's genuinely
    the bytes that were uploaded — they just don't contain the skill they claim to)."""
    server, static_dir = static_file_server
    other_skill_dir = tmp_path / "src" / "other" / "thing"
    other_skill_dir.mkdir(parents=True)
    (other_skill_dir / "SKILL.md").write_text(
        "---\nname: thing\ndescription: unrelated skill.\n---\nbody\n", encoding="utf-8"
    )
    (other_skill_dir / "skill.yaml").write_text(
        "manifestVersion: 1\nnamespace: other\nname: thing\nversion: 0.1.0\n"
        "description: unrelated skill.\nauthor: tester\nlicense: MIT\nruntime: claude-agent-skill\n"
        "targets: [claude]\n",
        encoding="utf-8",
    )
    result = pack_skill(other_skill_dir, static_dir)

    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    with pytest.raises(InstallError, match="content mismatch"):
        install_skill("excel/pivot-analysis@0.1.0", cfg=cfg, source_override=url)

    assert not (cfg.skills_dir / "excel" / "pivot-analysis").exists()


def test_install_rejects_mislabeled_artifact_wrong_version(tmp_path: Path, static_file_server) -> None:
    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)  # skill.yaml declares version 0.1.0
    result = pack_skill(skill_dir, static_dir)

    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"

    # Ask to install it as if it were 0.2.0 (e.g. a mislabeled/re-tagged Release).
    with pytest.raises(InstallError, match="content mismatch"):
        install_skill("excel/pivot-analysis@0.2.0", cfg=cfg, source_override=url)


def test_bad_reinstall_does_not_clobber_existing_good_install(tmp_path: Path, static_file_server) -> None:
    server, static_dir = static_file_server
    skill_dir = _make_skill(tmp_path)
    result = pack_skill(skill_dir, static_dir)
    cfg = SkillifyConfig(home=tmp_path / "home")
    url = f"http://127.0.0.1:{server.server_port}/{result.tarball_path.name}"
    install_skill("excel/pivot-analysis@0.1.0", cfg=cfg, source_override=url)
    good_skill_md = (cfg.skills_dir / "excel" / "pivot-analysis" / "SKILL.md").read_text(encoding="utf-8")

    # A second, mislabeled artifact for a version bump must not destroy the working install.
    other_skill_dir = tmp_path / "src2" / "other" / "thing"
    other_skill_dir.mkdir(parents=True)
    (other_skill_dir / "SKILL.md").write_text(
        "---\nname: thing\ndescription: unrelated.\n---\nbody\n", encoding="utf-8"
    )
    (other_skill_dir / "skill.yaml").write_text(
        "manifestVersion: 1\nnamespace: other\nname: thing\nversion: 0.2.0\n"
        "description: unrelated.\nauthor: tester\nlicense: MIT\nruntime: claude-agent-skill\n"
        "targets: [claude]\n",
        encoding="utf-8",
    )
    bad_result = pack_skill(other_skill_dir, static_dir)
    bad_url = f"http://127.0.0.1:{server.server_port}/{bad_result.tarball_path.name}"

    with pytest.raises(InstallError):
        install_skill("excel/pivot-analysis@0.2.0", cfg=cfg, source_override=bad_url)

    still_there = (cfg.skills_dir / "excel" / "pivot-analysis" / "SKILL.md").read_text(encoding="utf-8")
    assert still_there == good_skill_md
    stored_lock = read_lock(cfg.locks_dir, "excel", "pivot-analysis")
    assert stored_lock.version == "0.1.0"


def test_verify_checksum_ok_and_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    import hashlib

    good = hashlib.sha256(b"hello world").hexdigest()
    verify_checksum(f, good)  # does not raise
    with pytest.raises(ChecksumMismatch):
        verify_checksum(f, "0" * 64)


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    evil_tar = tmp_path / "evil.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tar:
        info = tarfile.TarInfo(name="../../evil.txt")
        data = b"pwned"
        info.size = len(data)
        import io

        tar.addfile(info, io.BytesIO(data))

    dest = tmp_path / "dest"
    with pytest.raises(UnsafeArchive):
        safe_extract(evil_tar, dest)


def test_safe_extract_rejects_device_files(tmp_path: Path) -> None:
    evil_tar = tmp_path / "evil-dev.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tar:
        info = tarfile.TarInfo(name="fake-device")
        info.type = tarfile.CHRTYPE
        info.devmajor = 1
        info.devminor = 1
        tar.addfile(info)

    with pytest.raises(UnsafeArchive, match="device"):
        safe_extract(evil_tar, tmp_path / "dest")


def test_safe_extract_works_without_data_filter_support(tmp_path: Path, monkeypatch) -> None:
    """F5: on Python patch versions without tarfile's `filter='data'` (PEP 706 backport),
    safe_extract must still work and still reject unsafe members via its own checks."""
    import skillify.install.extract as extract_module

    monkeypatch.setattr(extract_module, "_HAS_DATA_FILTER", False)

    good_tar = tmp_path / "good.tar.gz"
    with tarfile.open(good_tar, "w:gz") as tar:
        info = tarfile.TarInfo(name="SKILL.md")
        data = b"hello"
        info.size = len(data)
        import io

        tar.addfile(info, io.BytesIO(data))

    dest = tmp_path / "dest"
    safe_extract(good_tar, dest)
    assert (dest / "SKILL.md").read_bytes() == b"hello"

    evil_tar = tmp_path / "evil.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tar:
        info = tarfile.TarInfo(name="../escape.txt")
        data = b"pwned"
        info.size = len(data)
        import io

        tar.addfile(info, io.BytesIO(data))

    with pytest.raises(UnsafeArchive):
        safe_extract(evil_tar, tmp_path / "dest2")
