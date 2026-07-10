"""Guard against spec/ and the packaged schema resource drifting apart (T0.1/T0.2)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_packaged_schema_matches_spec_source_of_truth() -> None:
    spec_schema = (REPO_ROOT / "spec" / "skill-manifest-v1.schema.json").read_text(encoding="utf-8")
    packaged_schema = (
        resources.files("skillify.validator.schemas")
        .joinpath("skill-manifest-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    assert spec_schema == packaged_schema, (
        "spec/skill-manifest-v1.schema.json and the packaged copy under "
        "src/skillify/validator/schemas/ have drifted — edit the spec copy and re-sync."
    )
