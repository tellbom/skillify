"""Tests for T0.2 — the standard-format validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from skillify.validator import validate_skill_dir
from tests.fixtures import VALID_MANIFEST, VALID_SKILL_MD


def _write_skill(
    tmp_path: Path,
    *,
    dirname: str = "pivot-analysis",
    skill_md: str | None = VALID_SKILL_MD,
    manifest: str | None = VALID_MANIFEST,
    extra_files: dict[str, str] | None = None,
) -> Path:
    skill_dir = tmp_path / dirname
    skill_dir.mkdir(parents=True)
    if skill_md is not None:
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    if manifest is not None:
        (skill_dir / "skill.yaml").write_text(manifest, encoding="utf-8")
    for name, content in (extra_files or {}).items():
        path = skill_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return skill_dir


def test_valid_skill_passes(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path)
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(i) for i in result.issues]


def test_valid_skill_passes_namespace_aware(tmp_path: Path) -> None:
    namespace_dir = tmp_path / "excel"
    namespace_dir.mkdir()
    skill_dir = namespace_dir / "pivot-analysis"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")
    result = validate_skill_dir(skill_dir, namespace_aware=True)
    assert result.ok, [str(i) for i in result.issues]


def test_missing_skill_md(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, skill_md=None)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("SKILL.md" in i.path for i in result.issues)


def test_missing_skill_yaml(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, manifest=None)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any(i.path == "skill.yaml" for i in result.issues)


def test_skill_md_missing_frontmatter_fields(tmp_path: Path) -> None:
    bad_md = "---\nname: pivot-analysis\n---\nbody\n"
    skill_dir = _write_skill(tmp_path, skill_md=bad_md)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("frontmatter.description" in i.path for i in result.issues)


def test_bad_manifest_version(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST.replace("manifestVersion: 1", "manifestVersion: 2")
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("manifestVersion" in i.path for i in result.issues)


def test_bad_semver(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST.replace("version: 0.1.0", "version: not-a-version")
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("version" in i.path for i in result.issues)


def test_namespace_name_mismatch(tmp_path: Path) -> None:
    namespace_dir = tmp_path / "wrong-namespace"
    namespace_dir.mkdir()
    skill_dir = namespace_dir / "pivot-analysis"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(VALID_MANIFEST, encoding="utf-8")
    result = validate_skill_dir(skill_dir, namespace_aware=True)
    assert not result.ok
    assert any(i.path == "skill.yaml:namespace" for i in result.issues)


def test_unknown_field_rejected(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + "\nunknownField: true\n"
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert not result.ok


def test_opencode_entrypoints_reference_regular_files_inside_artifact(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + """
entrypoints:
  agents: {reviewer: agents/reviewer.md}
  commands: {review: commands/review.md}
  plugins: {governed-tools: plugins/governed-tools.js}
  mcp: {repo-search: mcp/repo-search.yaml}
"""
    skill_dir = _write_skill(
        tmp_path,
        manifest=manifest,
        extra_files={
            "agents/reviewer.md": "reviewer",
            "commands/review.md": "review",
            "plugins/governed-tools.js": "export default {}",
            "mcp/repo-search.yaml": "name: repo-search",
        },
    )
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(issue) for issue in result.issues]


@pytest.mark.parametrize(
    "entrypoints",
    [
        "{unknown: {name: commands/review.md}}",
        "{commands: {'Bad_Name': commands/review.md}}",
        "{commands: {review: /absolute/review.md}}",
        "{commands: {review: ../outside.md}}",
        "{commands: {review: commands/./review.md}}",
        "{commands: {review: commands//review.md}}",
        "{commands: {review: missing.md}}",
    ],
)
def test_opencode_entrypoints_reject_unknown_names_and_unsafe_paths(
    tmp_path: Path, entrypoints: str
) -> None:
    skill_dir = _write_skill(
        tmp_path,
        manifest=VALID_MANIFEST + f"\nentrypoints: {entrypoints}\n",
        extra_files={"commands/review.md": "review"},
    )
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("entrypoints" in issue.path for issue in result.issues)


def test_opencode_entrypoint_rejects_symlink_even_when_target_is_inside(tmp_path: Path) -> None:
    skill_dir = _write_skill(
        tmp_path,
        manifest=VALID_MANIFEST + "\nentrypoints: {commands: {review: commands/link.md}}\n",
        extra_files={"commands/real.md": "review"},
    )
    (skill_dir / "commands/link.md").symlink_to(skill_dir / "commands/real.md")
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("symlink" in issue.message for issue in result.issues)


def test_packaged_and_public_manifest_schemas_stay_identical() -> None:
    repository = Path(__file__).resolve().parents[1]
    packaged = repository / "src/skillify/validator/schemas/skill-manifest-v1.schema.json"
    public = repository / "spec/skill-manifest-v1.schema.json"
    assert packaged.read_bytes() == public.read_bytes()


def test_python_deps_require_requirements_file(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + "\ndependencies:\n  python: ['requests>=2.31']\n"
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any(i.path == "directory:requirements.txt" for i in result.issues)


def test_python_deps_with_requirements_file_passes(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + "\ndependencies:\n  python: ['requests>=2.31']\n"
    skill_dir = _write_skill(
        tmp_path, manifest=manifest, extra_files={"requirements.txt": "requests>=2.31\n"}
    )
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(i) for i in result.issues]


def test_claude_runtime_requires_claude_target(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST.replace("targets: [claude]", "targets: [opencode]")
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any(i.path == "skill.yaml:targets" for i in result.issues)


def test_bad_skill_dependency_range(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + "\ndependencies:\n  skills: ['excel/lookup@not-a-range']\n"
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("dependencies.skills[0]" in i.path for i in result.issues)


def test_good_skill_dependency_ranges(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + (
        "\ndependencies:\n"
        "  skills: ['excel/lookup@^1.2.3', 'excel/chart@>=2.0.0', 'excel/table@1.0.0']\n"
    )
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(i) for i in result.issues]


def test_invalid_yaml(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, manifest="not: valid: yaml: [")
    result = validate_skill_dir(skill_dir)
    assert not result.ok


def test_structured_permissions_manifest_passes(tmp_path: Path) -> None:
    manifest = VALID_MANIFEST + """
permissions:
  readPaths: [docs/**]
  writePaths: [output/**]
  commands:
    "python -m pytest *": ask
    "rm *": deny
  networkDomains: [docs.internal, "*.example.com"]
  mcpServers: [filesystem]
  databaseResources: [analytics]
  unattended: false
  confirm: [command, database]
"""
    skill_dir = _write_skill(tmp_path, manifest=manifest)
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(issue) for issue in result.issues]


def test_legacy_string_permissions_manifest_remains_valid(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path, manifest=VALID_MANIFEST + "\npermissions: [network]\n")
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(issue) for issue in result.issues]


def test_legacy_permission_string_length_remains_backward_compatible(tmp_path: Path) -> None:
    legacy = "legacy-" + "x" * 256
    skill_dir = _write_skill(
        tmp_path, manifest=VALID_MANIFEST + f"\npermissions: [{legacy}]\n"
    )
    result = validate_skill_dir(skill_dir)
    assert result.ok, [str(issue) for issue in result.issues]


@pytest.mark.parametrize(
    "permissions",
    [
        "{unknown: []}",
        "{readPaths: ../private}",
        "{commands: {'echo *': sometimes}}",
        "{networkDomains: ['https://example.com']}",
        "{confirm: [unknown]}",
    ],
)
def test_structured_permissions_rejects_unknown_or_malformed_values(
    tmp_path: Path, permissions: str
) -> None:
    skill_dir = _write_skill(
        tmp_path, manifest=VALID_MANIFEST + f"\npermissions: {permissions}\n"
    )
    result = validate_skill_dir(skill_dir)
    assert not result.ok
    assert any("permissions" in issue.path for issue in result.issues)
