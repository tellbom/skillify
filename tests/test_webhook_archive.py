"""Tests for T2.1b — Forgejo source-archive download + skill-root unwrap."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from skillify.publish.forgejo_client import ForgejoClient
from skillify.webhook.archive import fetch_and_extract_archive, resolve_archive_root
from tests.fake_forgejo import fake_forgejo  # noqa: F401


def _make_archive_bytes(files: dict[str, bytes], *, wrap_dir: str | None) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, content in files.items():
                arcname = f"{wrap_dir}/{name}" if wrap_dir else name
                info = tarfile.TarInfo(name=arcname)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_resolve_archive_root_unwraps_single_subdir(tmp_path: Path) -> None:
    root = tmp_path / "extracted"
    (root / "repo-abc123").mkdir(parents=True)
    (root / "repo-abc123" / "skill.yaml").write_text("manifestVersion: 1\n", encoding="utf-8")

    resolved = resolve_archive_root(root)
    assert resolved == root / "repo-abc123"


def test_resolve_archive_root_flat_already_correct(tmp_path: Path) -> None:
    root = tmp_path / "extracted"
    root.mkdir()
    (root / "skill.yaml").write_text("manifestVersion: 1\n", encoding="utf-8")

    resolved = resolve_archive_root(root)
    assert resolved == root


def test_fetch_and_extract_archive_end_to_end(tmp_path: Path, fake_forgejo) -> None:
    archive_bytes = _make_archive_bytes(
        {
            "SKILL.md": b"---\nname: pivot-analysis\ndescription: x\n---\nbody\n",
            "skill.yaml": (
                b"manifestVersion: 1\nnamespace: excel\nname: pivot-analysis\nversion: 0.1.0\n"
                b"description: x\nauthor: t\nlicense: MIT\nruntime: claude-agent-skill\ntargets: [claude]\n"
            ),
        },
        wrap_dir="pivot-analysis-abcdef",
    )
    fake_forgejo.state.archives["excel/pivot-analysis/v0.1.0"] = archive_bytes

    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    skill_root = fetch_and_extract_archive(client, "excel", "pivot-analysis", "v0.1.0", tmp_path / "work")

    assert (skill_root / "skill.yaml").is_file()
    assert (skill_root / "SKILL.md").is_file()


def test_fetch_and_extract_archive_missing_ref_raises(tmp_path: Path, fake_forgejo) -> None:
    from skillify.publish.forgejo_client import ForgejoError

    client = ForgejoClient(f"http://127.0.0.1:{fake_forgejo.server_port}", "tok")
    with pytest.raises(ForgejoError):
        fetch_and_extract_archive(client, "excel", "pivot-analysis", "v9.9.9", tmp_path / "work")
