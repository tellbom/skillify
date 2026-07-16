from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from skillify.apps import load_app_contract
from skillify.apps.local_doc_search import (
    DirectoryAliases,
    LocalDocumentSearch,
    content_for_upload,
)


ROOT = Path(__file__).parents[1]


def _search(tmp_path: Path, *, max_file_bytes: int = 100) -> tuple[Path, LocalDocumentSearch]:
    root = tmp_path / "documents"
    root.mkdir()
    aliases = DirectoryAliases()
    aliases.register("handbook", root)
    return root, LocalDocumentSearch(aliases, max_file_bytes=max_file_bytes)


def test_app_manifest_is_a_closed_published_contract() -> None:
    value = yaml.safe_load((ROOT / "apps/local-doc-search/app.yaml").read_text(encoding="utf-8"))
    contract = load_app_contract(value)
    assert contract.app_id == "local-doc-search"
    assert contract.workflow.version == "1.0.0"


def test_filename_metadata_and_fulltext_search_by_alias(tmp_path: Path) -> None:
    root, search = _search(tmp_path)
    (root / "leave-policy.md").write_text("Annual leave requires manager approval.\n", encoding="utf-8")

    assert search.search("handbook", "leave", mode="filename")[0].path == "leave-policy.md"
    assert search.search("handbook", ".md", mode="metadata")[0].suffix == ".md"
    match = search.search("handbook", "manager approval", mode="fulltext")[0]
    assert (match.path, match.line) == ("leave-policy.md", 1)


def test_ignore_size_and_sensitive_directory_rules(tmp_path: Path) -> None:
    root, search = _search(tmp_path, max_file_bytes=20)
    (root / "visible.txt").write_text("searchable", encoding="utf-8")
    (root / "large.txt").write_text("searchable" * 10, encoding="utf-8")
    (root / ".env").write_text("searchable", encoding="utf-8")
    (root / ".ssh").mkdir()
    (root / ".ssh/id.txt").write_text("searchable", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules/pkg.txt").write_text("searchable", encoding="utf-8")
    link = root / "linked.txt"
    try:
        link.symlink_to(root / "visible.txt")
    except OSError:
        pass

    assert [item.path for item in search.search("handbook", "searchable")] == ["visible.txt"]


def test_content_upload_requires_separate_confirmation(tmp_path: Path) -> None:
    root, search = _search(tmp_path)
    (root / "policy.txt").write_text("local only", encoding="utf-8")
    match = search.search("handbook", "local only")[0]
    with pytest.raises(PermissionError, match="confirmation"):
        content_for_upload(root, match, confirmed=False)
    assert content_for_upload(root, match, confirmed=True) == b"local only"


def test_server_facing_value_is_alias_not_directory_path(tmp_path: Path) -> None:
    root, search = _search(tmp_path)
    assert search.aliases.aliases() == ("handbook",)
    assert str(root) not in repr(search.aliases.aliases())
    with pytest.raises(ValueError, match="not registered"):
        search.search(str(root), "anything")
