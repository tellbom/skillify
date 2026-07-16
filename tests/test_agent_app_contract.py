from __future__ import annotations

import jsonschema
import pytest

from skillify.apps.contract import load_app_contract


def _contract() -> dict:
    return {
        "schemaVersion": 1,
        "appId": "local-doc-search",
        "version": "1.0.0",
        "workflow": {"id": "document-search", "version": "1.2.0", "status": "published"},
        "skills": [{"id": "text-search", "version": "2.0.1", "status": "published"}],
        "permissions": {
            "readPaths": ["*"], "writePaths": [], "commands": {},
            "networkDomains": [], "mcpServers": [], "databaseResources": [],
            "unattended": False, "confirm": ["read"],
        },
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["directoryAlias", "query"],
            "properties": {
                "directoryAlias": {"type": "string", "minLength": 1},
                "query": {"type": "string", "minLength": 1},
            },
        },
        "outputSchema": {
            "type": "object", "additionalProperties": False,
            "required": ["matches"],
            "properties": {"matches": {"type": "array"}},
        },
    }


def test_contract_locks_published_workflow_skills_permissions_and_schemas() -> None:
    contract = load_app_contract(_contract())
    assert (contract.workflow.id, contract.workflow.version) == ("document-search", "1.2.0")
    assert [(item.id, item.version) for item in contract.skills] == [("text-search", "2.0.1")]
    contract.validate_input({"directoryAlias": "handbook", "query": "leave policy"})
    contract.validate_output({"matches": []})
    with pytest.raises(jsonschema.ValidationError):
        contract.validate_input({"directoryAlias": "handbook", "query": "x", "shell": "rm"})


def test_contract_rejects_draft_capabilities_and_inline_scripts() -> None:
    draft = _contract()
    draft["workflow"] = {"id": "document-search", "version": "1.2.0", "status": "draft"}
    with pytest.raises(ValueError, match="published"):
        load_app_contract(draft)

    scripted = _contract()
    scripted["inlineScript"] = "print('unreviewed')"
    with pytest.raises(ValueError, match="Additional properties"):
        load_app_contract(scripted)


def test_contract_rejects_open_ended_input_or_output_objects() -> None:
    value = _contract()
    value["inputSchema"].pop("additionalProperties")
    with pytest.raises(ValueError, match="closed object"):
        load_app_contract(value)
