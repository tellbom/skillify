from pathlib import Path

from skillify.validator import validate_skill_dir
from skillify.workflows import approval_required, load_workflow_pack


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/feature"


def test_feature_pack_and_configurable_plan_approval_gate() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert pack.runtimes == ("opencode", "claude-code")
    assert pack.entry_agent == "build"
    assert "test-driven-development" in pack.skills
    assert approval_required(pack, "plan-approval", origin="web") is True
    assert approval_required(pack, "plan-approval", origin="local") is False
    assert approval_required(pack, "plan-approval", origin="web", override=False) is False
    assert approval_required(pack, "plan-approval", origin="local", override=True) is True
