from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from skillify.agent.fake_provider import FakeProvider
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
from skillify.validator import validate_skill_dir
from skillify.workflows import execute_workflow, load_workflow_pack


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/onboarding"


def _start(tmp_path: Path) -> ProviderStartSpec:
    workspace = (tmp_path / "repo").resolve()
    workspace.mkdir()
    return ProviderStartSpec(
        workspace=workspace,
        allowed_paths=(workspace,),
        config_dir=tmp_path / "config",
        runtime=ModelRuntimeConfig(
            "fake", "https://model.internal/v1", "fake-model",
            ("model.internal",), ("MODEL_TOKEN",),
        ),
    )


@pytest.mark.parametrize("repository_profile", ["python-service", "vue-app", "go-cli"])
def test_onboarding_three_repository_golden_runs(
    tmp_path: Path,
    repository_profile: str,
) -> None:
    pack = load_workflow_pack(PACK_PATH)
    ids = iter((f"handle-{repository_profile}", "session-1", "session-2", "session-3"))
    provider = FakeProvider(
        clock=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
        id_factory=lambda: next(ids),
    )

    result = execute_workflow(pack, provider, _start(tmp_path))

    assert result.completed_roles == (
        "repository-analysis", "architecture-summary", "risk-and-test-entry",
    )
    assert result.artifacts == ("project-brief.md",)
    assert provider.live_handle_count == provider.live_session_count == 0


def test_onboarding_pack_is_valid_read_only_and_evidence_linked() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert pack.mode == "read-only"
    assert all(role.requires_evidence for role in pack.roles)
    template = (PACK_PATH / "project-brief.md").read_text(encoding="utf-8")
    assert "path:line" in template
