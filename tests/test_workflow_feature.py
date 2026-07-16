from pathlib import Path
import shutil

import pytest
import yaml

from skillify.validator import validate_skill_dir
from skillify.workflows import approval_required, load_workflow_pack


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/feature"


def test_feature_pack_and_configurable_plan_approval_gate() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert pack.runtimes == ("opencode", "claude-code")
    assert pack.entry_agent == "build"
    assert pack.delegation.mode == "suggested"
    assert pack.delegation.executor_managed is True
    assert "test-driven-development" in pack.skills
    assert approval_required(pack, "plan-approval", origin="web") is True
    assert approval_required(pack, "plan-approval", origin="local") is False
    assert approval_required(pack, "plan-approval", origin="web", override=False) is False
    assert approval_required(pack, "plan-approval", origin="local", override=True) is True


@pytest.mark.parametrize("mode", ["adaptive", "suggested", "required"])
def test_workflow_pack_supports_executor_managed_delegation_modes(tmp_path, mode: str) -> None:
    target = tmp_path / "feature"
    shutil.copytree(PACK_PATH, target)
    path = target / "workflow.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    value["delegation"] = {
        "mode": mode, "user_approval": "required", "executor_managed": True,
    }
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    assert load_workflow_pack(target).delegation.mode == mode
