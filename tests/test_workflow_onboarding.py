from pathlib import Path

from skillify.validator import validate_skill_dir
from skillify.workflows import load_workflow_pack


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/onboarding"


def test_onboarding_pack_is_provider_configuration_not_a_role_executor() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert pack.mode == "read-only"
    assert pack.runtimes == ("opencode", "claude-code")
    assert pack.entry_agent == "plan"
    assert pack.skills == ("codegraph-exploration", "project-onboarding", "evidence-reporting")
    assert pack.artifacts == ("project-brief.md",)
    assert pack.permissions.write_paths == ()
    assert "path:line" in (PACK_PATH / "project-brief.md").read_text(encoding="utf-8")
