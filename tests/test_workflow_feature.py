from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from skillify.agent.fake_provider import FakeProvider
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
from skillify.validator import validate_skill_dir
from skillify.workflows import (
    approval_required,
    execute_workflow,
    load_workflow_pack,
)


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/feature"


def _start(tmp_path: Path) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve()
    workspace.mkdir()
    return ProviderStartSpec(
        workspace, (workspace,), tmp_path / "config",
        ModelRuntimeConfig(
            "fake", "https://model.internal/v1", "fake-model",
            ("model.internal",), ("MODEL_TOKEN",),
        ),
    )


def test_feature_pack_and_configurable_plan_approval_gate() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert approval_required(pack, "plan-approval", origin="web") is True
    assert approval_required(pack, "plan-approval", origin="local") is False
    assert approval_required(pack, "plan-approval", origin="web", override=False) is False
    assert approval_required(pack, "plan-approval", origin="local", override=True) is True


def test_feature_fake_provider_runs_roles_serially(tmp_path: Path) -> None:
    ids = iter(("handle", "s1", "s2", "s3", "s4", "s5"))
    provider = FakeProvider(
        clock=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
        id_factory=lambda: next(ids),
    )

    result = execute_workflow(load_workflow_pack(PACK_PATH), provider, _start(tmp_path))

    assert result.completed_roles == (
        "clarification", "localization", "plan", "tdd-implementation", "review",
    )
    assert result.artifacts == ("feature-report.md", "change.patch")
