from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from skillify.agent.fake_provider import FakeProvider
from skillify.agent.provider import ModelRuntimeConfig, ProviderStartSpec
from skillify.validator import validate_skill_dir
from skillify.workflows import execute_workflow, load_workflow_pack


ROOT = Path(__file__).parents[1]
PACK_PATH = ROOT / "workflows/bugfix"


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


def test_bugfix_pack_structure_and_evidence_gate() -> None:
    assert validate_skill_dir(PACK_PATH).ok
    pack = load_workflow_pack(PACK_PATH)
    assert pack.mode == "workspace-write"
    assert tuple(role.id for role in pack.roles) == (
        "reproduce", "root-cause", "implementation", "test", "review",
    )
    gate = pack.gates[0]
    assert (gate.id, gate.before_role, gate.required_by_default) == (
        "reproduction-evidence", "implementation", True,
    )
    assert pack.roles[0].requires_evidence


def test_bugfix_fake_provider_golden_run(tmp_path: Path) -> None:
    ids = iter(("handle", "s1", "s2", "s3", "s4", "s5"))
    provider = FakeProvider(
        clock=lambda: datetime(2026, 7, 16, tzinfo=timezone.utc),
        id_factory=lambda: next(ids),
    )

    result = execute_workflow(load_workflow_pack(PACK_PATH), provider, _start(tmp_path))

    assert result.completed_roles == (
        "reproduce", "root-cause", "implementation", "test", "review",
    )
    assert result.artifacts == ("bugfix-report.md", "change.patch")
    assert provider.live_handle_count == provider.live_session_count == 0


def test_bugfix_report_contains_required_evidence_sections() -> None:
    report = (PACK_PATH / "bugfix-report.md").read_text(encoding="utf-8")
    for heading in ("Reproduction", "Root cause", "Patch", "Verification", "Remaining risks"):
        assert f"## {heading}" in report
