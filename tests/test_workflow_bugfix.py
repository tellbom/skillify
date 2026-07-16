from pathlib import Path

from skillify.validator import validate_skill_dir
from skillify.workflows import approval_required, load_workflow_pack


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/bugfix"


def test_bugfix_pack_declares_provider_skills_permissions_and_evidence_gate() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert pack.mode == "workspace-write"
    assert pack.entry_agent == "build"
    assert "systematic-debugging" in pack.skills
    assert pack.permissions.write_paths == ("*",)
    assert approval_required(pack, "reproduction-evidence", origin="local") is True


def test_bugfix_report_contains_required_evidence_sections() -> None:
    report = (PACK_PATH / "bugfix-report.md").read_text(encoding="utf-8")
    for heading in ("Reproduction", "Root cause", "Patch", "Verification", "Remaining risks"):
        assert f"## {heading}" in report
