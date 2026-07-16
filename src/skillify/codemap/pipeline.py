"""Bounded offline Code Map discovery and symbol extraction pipeline."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


GENERATOR_VERSION = "1.0.0"
_LANGUAGES = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
}
_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__",
    "node_modules", "vendor", "dist", "build", "coverage", "generated",
})
_SECRET_NAMES = frozenset({
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials.json", "secrets.json",
})


class CodeMapBuildError(ValueError):
    """Repository input or pipeline configuration is invalid."""


def _safe_relative(value: str) -> bool:
    pure = PurePosixPath(value)
    return (
        bool(pure.parts)
        and not pure.is_absolute()
        and pure.as_posix() == value
        and not any(part in {"", ".", ".."} for part in pure.parts)
        and not any(part in _EXCLUDED_DIRS for part in pure.parts[:-1])
        and pure.name not in _SECRET_NAMES
        and not pure.name.startswith(".env.")
    )


def _discover_with_rg(root: Path) -> list[str] | None:
    executable = shutil.which("rg")
    if executable is None:
        return None
    command = [
        executable, "--files", "--null", "--hidden",
        "--glob", "!.git/**", "--glob", "!.hg/**", "--glob", "!.svn/**",
        "--glob", "!.venv/**", "--glob", "!venv/**",
        "--glob", "!node_modules/**", "--glob", "!vendor/**",
        "--glob", "!dist/**", "--glob", "!build/**",
        "--glob", "!coverage/**", "--glob", "!generated/**",
        "--glob", "!.env*", "--glob", "!id_rsa", "--glob", "!id_ed25519",
    ]
    completed = subprocess.run(
        command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=False, timeout=30,
    )
    if completed.returncode not in {0, 1}:
        return None
    return [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def _discover(root: Path) -> list[str]:
    discovered = _discover_with_rg(root)
    if discovered is None:
        discovered = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        ]
    return sorted({
        relative for relative in discovered
        if _safe_relative(relative) and Path(relative).suffix.lower() in _LANGUAGES
    })


def _symbol(name: str, kind: str, line: int, end_line: int, parser: str) -> dict[str, Any]:
    return {
        "name": name,
        "kind": kind,
        "line": line,
        "endLine": max(line, end_line),
        "parser": parser,
    }


def _python_symbols(text: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], f"{exc.msg} at line {exc.lineno or 1}"
    symbols = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(_symbol(
                node.name, "function", node.lineno,
                getattr(node, "end_lineno", node.lineno), "python-ast",
            ))
        elif isinstance(node, ast.ClassDef):
            symbols.append(_symbol(
                node.name, "class", node.lineno,
                getattr(node, "end_lineno", node.lineno), "python-ast",
            ))
    return sorted(symbols, key=lambda item: (item["line"], item["name"])), None


_PATTERNS = {
    "javascript": (
        ("class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
        ("function", re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")),
    ),
    "typescript": (
        ("class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)")),
        ("interface", re.compile(r"\binterface\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
    ),
    "java": (
        ("class", re.compile(r"\b(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)")),
        ("method", re.compile(r"\b(?:public|protected|private|static|final|synchronized|native|abstract|\s)+[\w<>,.?\[\]]+\s+([A-Za-z_$][\w$]*)\s*\(")),
    ),
    "go": (
        ("function", re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(")),
        ("type", re.compile(r"^\s*type\s+([A-Za-z_]\w*)\s+")),
    ),
}


def _pattern_symbols(text: str, language: str) -> tuple[list[dict[str, Any]], str | None]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS[language]:
            match = pattern.search(line)
            if match:
                symbols.append(_symbol(
                    match.group(1), kind, line_number, line_number,
                    "pattern-fallback-v1",
                ))
    return symbols, None


def _summary(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:160]
    return ""


def _repository_hash(files: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(item["contentHash"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_code_map(
    repository: Path,
    *,
    output_path: Path | None = None,
    previous: Mapping[str, Any] | None = None,
    max_files: int = 10_000,
    max_file_bytes: int = 2 * 1024 * 1024,
) -> dict[str, Any]:
    root = Path(repository).absolute()
    if not root.is_dir():
        raise CodeMapBuildError("repository must be an existing directory")
    if type(max_files) is not int or max_files < 1:
        raise CodeMapBuildError("max_files must be a positive integer")
    if type(max_file_bytes) is not int or max_file_bytes < 1:
        raise CodeMapBuildError("max_file_bytes must be a positive integer")

    discovered = _discover(root)
    selected = discovered[:max_files]
    previous_files = {
        item.get("path"): item
        for item in (previous or {}).get("files", [])
        if type(item) is dict and type(item.get("path")) is str
    }
    files: list[dict[str, Any]] = []
    reused = 0
    skipped: list[str] = []
    for relative in selected:
        path = root / relative
        try:
            content = path.read_bytes()
        except OSError:
            skipped.append(relative)
            continue
        if len(content) > max_file_bytes or b"\0" in content[:8192]:
            skipped.append(relative)
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(relative)
            continue
        content_hash = hashlib.sha256(content).hexdigest()
        old = previous_files.get(relative)
        if type(old) is dict and old.get("contentHash") == content_hash:
            files.append(dict(old))
            reused += 1
            continue
        language = _LANGUAGES[path.suffix.lower()]
        symbols, parse_error = (
            _python_symbols(text)
            if language == "python"
            else _pattern_symbols(text, language)
        )
        files.append({
            "path": relative,
            "language": language,
            "contentHash": content_hash,
            "size": len(content),
            "summary": _summary(text),
            "symbols": symbols,
            "parseError": parse_error,
        })

    current_by_path = {item["path"]: item for item in files}
    old_paths = set(previous_files)
    new_paths = set(current_by_path)
    added = sorted(new_paths - old_paths)
    deleted = sorted(old_paths - new_paths)
    renamed: list[dict[str, str]] = []
    for old_path in tuple(deleted):
        old_hash = previous_files[old_path].get("contentHash")
        match = next((
            new_path for new_path in added
            if current_by_path[new_path]["contentHash"] == old_hash
        ), None)
        if match is not None:
            renamed.append({"from": old_path, "to": match})
            deleted.remove(old_path)
            added.remove(match)
    modified = sorted(
        path for path in old_paths & new_paths
        if previous_files[path].get("contentHash") != current_by_path[path]["contentHash"]
    )
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "generator": {
            "name": "skillify-codemap",
            "version": GENERATOR_VERSION,
            "discovery": "ripgrep" if shutil.which("rg") else "pathlib-fallback",
            "symbolParsers": ["python-ast", "pattern-fallback-v1"],
        },
        "repositoryHash": _repository_hash(files),
        "summary": {
            "provider": "builtin-fallback",
            "text": f"{len(files)} indexed source files",
        },
        "files": files,
        "changes": {
            "added": added,
            "modified": modified,
            "deleted": deleted,
            "renamed": renamed,
        },
        "stats": {
            "discoveredFiles": len(discovered),
            "indexedFiles": len(files),
            "reusedFiles": reused,
            "skippedFiles": skipped,
            "truncated": len(discovered) > max_files,
        },
    }
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(
            json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    return result
