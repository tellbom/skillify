"""Governed Agent App contract with fixed schemas and published capability pins."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import jsonschema
import yaml

from skillify.agent.permissions import PermissionManifest


_ID = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_VERSION = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"

AGENT_APP_CONTRACT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schemaVersion", "appId", "version", "workflow", "skills",
        "permissions", "inputSchema", "outputSchema",
    ],
    "properties": {
        "schemaVersion": {"const": 1},
        "appId": {"type": "string", "pattern": _ID},
        "version": {"type": "string", "pattern": _VERSION},
        "workflow": {"$ref": "#/$defs/capability"},
        "skills": {"type": "array", "items": {"$ref": "#/$defs/capability"}},
        "permissions": {"type": "object"},
        "inputSchema": {"type": "object"},
        "outputSchema": {"type": "object"},
    },
    "$defs": {
        "capability": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "version", "status"],
            "properties": {
                "id": {"type": "string", "pattern": _ID},
                "version": {"type": "string", "pattern": _VERSION},
                "status": {"const": "published"},
            },
        },
    },
}


@dataclass(frozen=True)
class PublishedCapability:
    id: str
    version: str


@dataclass(frozen=True)
class AgentAppContract:
    app_id: str
    version: str
    workflow: PublishedCapability
    skills: tuple[PublishedCapability, ...]
    permissions: PermissionManifest
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]

    def validate_input(self, value: object) -> None:
        jsonschema.Draft202012Validator(self.input_schema).validate(value)

    def validate_output(self, value: object) -> None:
        jsonschema.Draft202012Validator(self.output_schema).validate(value)


def _capability(value: Mapping[str, Any]) -> PublishedCapability:
    return PublishedCapability(str(value["id"]), str(value["version"]))


def load_app_contract(value: object) -> AgentAppContract:
    try:
        jsonschema.Draft202012Validator(AGENT_APP_CONTRACT_SCHEMA).validate(value)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"invalid Agent App contract: {exc.message}") from exc
    assert isinstance(value, dict)
    input_schema = dict(value["inputSchema"])
    output_schema = dict(value["outputSchema"])
    for name, schema in (("input", input_schema), ("output", output_schema)):
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise ValueError(f"invalid Agent App {name} schema") from exc
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            raise ValueError(f"Agent App {name} schema must be a closed object")
    try:
        permissions = PermissionManifest.from_value(
            f"app-{value['appId']}-{value['version']}", value["permissions"],
        )
    except ValueError as exc:
        raise ValueError(f"invalid Agent App permissions: {exc}") from exc
    workflow = _capability(value["workflow"])
    skills = tuple(_capability(item) for item in value["skills"])
    if len({(item.id, item.version) for item in skills}) != len(skills):
        raise ValueError("Agent App skill pins must be unique")
    return AgentAppContract(
        str(value["appId"]), str(value["version"]), workflow, skills,
        permissions, input_schema, output_schema,
    )


def load_bundled_app_contract(app_id: str, root: Path | None = None) -> AgentAppContract:
    apps_root = Path(root) if root is not None else Path(__file__).resolve().parents[3] / "apps"
    path = apps_root / app_id / "app.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Agent App contract is unavailable: {app_id}") from exc
    contract = load_app_contract(value)
    if contract.app_id != app_id:
        raise ValueError("Agent App directory and contract id do not match")
    return contract
