"""Tests for M-B (docs/review-m2-m6.md) — `rehome_to_declared_name` must reject a
`declared_name` that isn't a bare path segment before touching the filesystem, since it's
fed from untrusted `skill.yaml` content (web upload) or repo name (webhook)."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillify.common.skill_dir import InvalidDeclaredName, rehome_to_declared_name


def test_rehome_moves_to_declared_name(tmp_path: Path) -> None:
    src = tmp_path / "arbitrary-extract-dir"
    src.mkdir()
    (src / "SKILL.md").write_text("x", encoding="utf-8")
    dest_root = tmp_path / "dest"

    result = rehome_to_declared_name(src, "pivot-analysis", dest_root)

    assert result == (dest_root / "pivot-analysis").resolve()
    assert result.is_dir()
    assert not src.exists()


def test_rehome_is_noop_when_already_at_destination(tmp_path: Path) -> None:
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    src = dest_root / "pivot-analysis"
    src.mkdir()

    result = rehome_to_declared_name(src, "pivot-analysis", dest_root)
    assert result == src.resolve()


@pytest.mark.parametrize(
    "declared_name",
    [
        "../escape",
        "../../etc",
        "a/b",
        "/absolute/path",
        "",
        "UPPERCASE",
        "-leading-dash",
        "trailing-dash-",
    ],
)
def test_rehome_rejects_unsafe_declared_name(tmp_path: Path, declared_name: str) -> None:
    src = tmp_path / "arbitrary-extract-dir"
    src.mkdir()
    dest_root = tmp_path / "dest"

    with pytest.raises(InvalidDeclaredName):
        rehome_to_declared_name(src, declared_name, dest_root)

    # Nothing was written outside dest_root, and src is untouched.
    assert src.is_dir()
    assert not any(tmp_path.glob("escape*"))
    assert not (tmp_path.parent / "escape").exists()


def test_rehome_rejects_absolute_path_that_would_replace_dest_root(tmp_path: Path) -> None:
    src = tmp_path / "arbitrary-extract-dir"
    src.mkdir()
    dest_root = tmp_path / "dest"
    evil_target = tmp_path / "evil-absolute-target"

    with pytest.raises(InvalidDeclaredName):
        rehome_to_declared_name(src, str(evil_target), dest_root)

    assert not evil_target.exists()
