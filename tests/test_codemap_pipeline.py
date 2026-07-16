from __future__ import annotations

from pathlib import Path

from skillify.codemap.pipeline import build_code_map


def _write(root: Path, relative: str, content: str | bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_build_indexes_supported_languages_and_excludes_unsafe_inputs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo, "app.py", "class Service:\n    def run(self):\n        return 1\n")
    _write(repo, "web/main.ts", "export function start() { return true }\n")
    _write(repo, "src/Main.java", "class Main { public void execute() {} }\n")
    _write(repo, "cmd/main.go", "package main\nfunc main() {}\n")
    _write(repo, ".env", "TOKEN=secret\n")
    _write(repo, "node_modules/pkg/index.js", "function hidden() {}\n")
    _write(repo, "image.bin", b"\x00\x01binary")

    result = build_code_map(repo)

    assert result["schemaVersion"] == 1
    assert result["generator"]["version"]
    assert [item["path"] for item in result["files"]] == [
        "app.py", "cmd/main.go", "src/Main.java", "web/main.ts",
    ]
    symbols = {symbol["name"] for item in result["files"] for symbol in item["symbols"]}
    assert {"Service", "run", "start", "Main", "execute", "main"} <= symbols
    assert len(result["repositoryHash"]) == 64
    assert result["summary"]["provider"] == "builtin-fallback"


def test_incremental_build_reuses_unchanged_and_tracks_delete_and_rename(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo, "keep.py", "def keep():\n    return 1\n")
    _write(repo, "old.py", "def moved():\n    return 2\n")
    first = build_code_map(repo)

    (repo / "old.py").rename(repo / "new.py")
    second = build_code_map(repo, previous=first)

    assert second["stats"]["reusedFiles"] == 1
    assert second["changes"]["renamed"] == [{"from": "old.py", "to": "new.py"}]
    assert second["changes"]["deleted"] == []
    assert second["changes"]["added"] == []

    (repo / "new.py").unlink()
    third = build_code_map(repo, previous=second)
    assert third["changes"]["deleted"] == ["new.py"]


def test_syntax_error_is_recorded_without_blocking_other_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo, "broken.py", "def broken(:\n")
    _write(repo, "valid.py", "def valid():\n    return True\n")

    result = build_code_map(repo)

    files = {item["path"]: item for item in result["files"]}
    assert files["broken.py"]["parseError"]
    assert files["broken.py"]["symbols"] == []
    assert files["valid.py"]["symbols"][0]["name"] == "valid"


def test_large_repository_is_bounded_deterministically(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    for index in range(12):
        _write(repo, f"pkg/file_{index:02d}.py", f"def f_{index}():\n    return {index}\n")

    result = build_code_map(repo, max_files=5)

    assert result["stats"]["truncated"] is True
    assert result["stats"]["discoveredFiles"] == 12
    assert [item["path"] for item in result["files"]] == [
        "pkg/file_00.py", "pkg/file_01.py", "pkg/file_02.py",
        "pkg/file_03.py", "pkg/file_04.py",
    ]


def test_output_is_written_as_versioned_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    output = tmp_path / "code-map.json"
    _write(repo, "main.py", "def main():\n    pass\n")

    result = build_code_map(repo, output_path=output)

    assert output.is_file()
    assert output.read_text(encoding="utf-8").endswith("\n")
    assert '"schemaVersion":1' in output.read_text(encoding="utf-8")
    assert result["files"][0]["contentHash"]
