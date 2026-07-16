from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from skillify.validator import validate_skill_dir
from skillify.workflows import load_workflow_pack


ROOT = Path(__file__).parents[1]
REVIEW = ROOT / "workflows/review"
REFACTOR = ROOT / "workflows/refactor"


def _schema(path: Path) -> dict[str, object]:
    return json.loads((path / "report.schema.json").read_text(encoding="utf-8"))


def test_review_pack_is_read_only_and_requires_finding_evidence() -> None:
    assert validate_skill_dir(REVIEW).ok
    pack = load_workflow_pack(REVIEW)
    assert pack.mode == "read-only"
    assert pack.entry_agent == "plan"
    assert pack.artifacts == ("review-report.json",)
    valid = {
        "summary": "One correctness finding.",
        "findings": [{
            "severity": "P1", "title": "Wrong branch",
            "impact": "Valid requests fail.",
            "evidence": {"path": "src/service.py", "line": 42},
        }],
    }
    jsonschema.validate(valid, _schema(REVIEW))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({
            "summary": "Speculative", "findings": [{
                "severity": "P3", "title": "Maybe", "impact": "Unknown",
            }],
        }, _schema(REVIEW))


def test_refactor_pack_requires_baseline_before_implementation() -> None:
    assert validate_skill_dir(REFACTOR).ok
    pack = load_workflow_pack(REFACTOR)
    assert pack.entry_agent == "build"
    assert "behavior-preserving-refactor" in pack.skills
    assert pack.gates[0].required_by_default is True


def test_refactor_report_schema_preserves_external_behavior() -> None:
    valid = {
        "baseline": {"commands": ["pytest tests/test_service.py"], "passed": True},
        "changes": ["Extracted duplicate parser."],
        "verification": {"commands": ["pytest tests/test_service.py"], "passed": True},
        "externalBehaviorChanged": False,
        "remainingRisks": [],
    }
    schema = _schema(REFACTOR)
    jsonschema.validate(valid, schema)
    invalid = dict(valid, externalBehaviorChanged=True)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)
