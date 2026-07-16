"""Bounded local filename, metadata, and full-text search by directory alias."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "node_modules", "vendor", "dist", "build",
    ".ssh", ".gnupg", ".aws", ".kube", "secrets", "credentials",
})
_SENSITIVE_FILES = frozenset({".env", "id_rsa", "id_ed25519", "credentials.json", "secrets.json"})
_TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".log", ".py", ".js", ".ts", ".java", ".go",
})


@dataclass(frozen=True)
class DocumentMatch:
    path: str
    size: int
    suffix: str
    line: int | None = None
    snippet: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path, "size": self.size, "suffix": self.suffix,
            "line": self.line, "snippet": self.snippet,
        }


class DirectoryAliases:
    def __init__(self) -> None:
        self._paths: dict[str, Path] = {}

    def register(self, alias: str, directory: Path) -> None:
        if not alias or not alias.replace("-", "").replace("_", "").isalnum():
            raise ValueError("directory alias is invalid")
        resolved = Path(directory).resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("alias target must be a directory")
        self._paths[alias] = resolved

    def resolve(self, alias: str) -> Path:
        try:
            return self._paths[alias]
        except KeyError as exc:
            raise ValueError("directory alias is not registered") from exc

    def aliases(self) -> tuple[str, ...]:
        return tuple(sorted(self._paths))


class LocalDocumentSearch:
    def __init__(self, aliases: DirectoryAliases, *, max_file_bytes: int = 1024 * 1024) -> None:
        self.aliases = aliases
        self.max_file_bytes = max_file_bytes

    def _files(self, root: Path):
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(
                name for name in dirs
                if name not in _IGNORED_DIRS and not name.startswith(".")
                and not (Path(current) / name).is_symlink()
            )
            for name in sorted(names):
                path = Path(current) / name
                if (
                    name in _SENSITIVE_FILES or name.startswith(".env.") or name.startswith(".")
                    or path.is_symlink() or not path.is_file()
                ):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size <= self.max_file_bytes:
                    yield path, size

    def search(
        self,
        alias: str,
        query: str,
        *,
        mode: str = "fulltext",
        max_results: int = 50,
    ) -> list[DocumentMatch]:
        if mode not in {"filename", "metadata", "fulltext"}:
            raise ValueError("search mode must be filename, metadata, or fulltext")
        if not query.strip() or not 1 <= max_results <= 500:
            raise ValueError("query and result limit are invalid")
        root = self.aliases.resolve(alias)
        needle = query.casefold()
        results: list[DocumentMatch] = []
        for path, size in self._files(root):
            relative = path.relative_to(root).as_posix()
            suffix = path.suffix.casefold()
            if mode == "filename" and needle in path.name.casefold():
                results.append(DocumentMatch(relative, size, suffix))
            elif mode == "metadata" and needle in f"{path.name} {suffix} {size}".casefold():
                results.append(DocumentMatch(relative, size, suffix))
            elif mode == "fulltext" and suffix in _TEXT_SUFFIXES:
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for line_number, line in enumerate(lines, start=1):
                    if needle in line.casefold():
                        results.append(DocumentMatch(relative, size, suffix, line_number, line.strip()[:240]))
                        break
            if len(results) >= max_results:
                break
        return results


def content_for_upload(root: Path, match: DocumentMatch, *, confirmed: bool) -> bytes:
    if not confirmed:
        raise PermissionError("content upload requires explicit confirmation")
    base = Path(root).resolve(strict=True)
    path = (base / match.path).resolve(strict=True)
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("document result no longer resolves inside the selected directory")
    return path.read_bytes()
