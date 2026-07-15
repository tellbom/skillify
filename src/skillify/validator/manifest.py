"""Validate skill.yaml against the v1 JSON Schema + the extra rules in spec §4."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from skillify.validator.errors import ValidationResult

_SCHEMA_CACHE: dict[str, Any] = {}

_SKILL_DEP_VERSION_RANGE_RE = re.compile(
    r"^(?:\^|~|>=|<=|>|<|=)?\s*\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


def _load_schema(manifest_version: int) -> dict[str, Any]:
    if manifest_version in _SCHEMA_CACHE:
        return _SCHEMA_CACHE[manifest_version]
    schema_name = f"skill-manifest-v{manifest_version}.schema.json"
    try:
        raw = (
            resources.files("skillify.validator.schemas")
            .joinpath(schema_name)
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise UnsupportedManifestVersion(manifest_version) from exc
    schema = json.loads(raw)
    _SCHEMA_CACHE[manifest_version] = schema
    return schema


class UnsupportedManifestVersion(Exception):
    def __init__(self, manifest_version: Any):
        super().__init__(f"unsupported manifestVersion: {manifest_version!r}")
        self.manifest_version = manifest_version


def load_manifest_yaml(skill_yaml_path: Path, result: ValidationResult) -> dict[str, Any] | None:
    """Parse skill.yaml as YAML. Returns None (and records an issue) on failure."""
    if not skill_yaml_path.is_file():
        result.add("skill.yaml", "file not found")
        return None
    try:
        text = skill_yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.add("skill.yaml", f"could not read file: {exc}")
        return None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        result.add("skill.yaml", f"invalid YAML: {exc}")
        return None
    if not isinstance(data, dict):
        result.add("skill.yaml", "top-level document must be a mapping")
        return None
    return data


def validate_manifest_schema(data: dict[str, Any], result: ValidationResult) -> None:
    manifest_version = data.get("manifestVersion")
    if manifest_version != 1:
        # Schema validation below still runs for well-formed dicts with a bad
        # version, but an unsupported version means we can't even pick a schema.
        if not isinstance(manifest_version, int):
            result.add("skill.yaml:manifestVersion", "must be an integer")
            return
        try:
            schema = _load_schema(manifest_version)
        except UnsupportedManifestVersion:
            result.add(
                "skill.yaml:manifestVersion",
                f"unsupported manifestVersion {manifest_version} "
                f"(this validator supports: 1)",
            )
            return
    else:
        schema = _load_schema(1)

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        json_path = "$" + "".join(
            f"[{p!r}]" if isinstance(p, str) else f"[{p}]" for p in error.path
        )
        result.add(f"skill.yaml:{json_path}", error.message)


def validate_manifest_semantics(
    data: dict[str, Any],
    result: ValidationResult,
    *,
    expected_namespace: str | None,
    expected_name: str | None,
) -> None:
    """Rules from spec §4 beyond plain JSON-Schema shape checks."""
    if expected_namespace is not None and data.get("namespace") != expected_namespace:
        result.add(
            "skill.yaml:namespace",
            f"namespace {data.get('namespace')!r} does not match directory "
            f"{expected_namespace!r}",
        )
    if expected_name is not None and data.get("name") != expected_name:
        result.add(
            "skill.yaml:name",
            f"name {data.get('name')!r} does not match directory {expected_name!r}",
        )

    runtime = data.get("runtime")
    targets = data.get("targets")
    if runtime == "claude-agent-skill" and isinstance(targets, list) and "claude" not in targets:
        result.add(
            "skill.yaml:targets",
            "runtime=claude-agent-skill requires 'claude' to be included in targets",
        )

    permissions = data.get("permissions", [])
    if isinstance(permissions, (list, dict)):
        try:
            from skillify.agent.permissions import PermissionManifest

            PermissionManifest.from_value("validator:manifest", permissions)
        except ValueError as exc:
            result.add("skill.yaml:permissions", str(exc))

    deps = data.get("dependencies") or {}
    for i, entry in enumerate(deps.get("skills", []) or []):
        if "@" not in entry:
            continue  # already caught by schema pattern
        _, _, version_range = entry.partition("@")
        if not _SKILL_DEP_VERSION_RANGE_RE.match(version_range.strip()):
            result.add(
                f"skill.yaml:dependencies.skills[{i}]",
                f"version range {version_range!r} is not a recognized semver range "
                "(expected e.g. '1.2.3', '^1.2.3', '~1.2.3', '>=1.2.3')",
            )
