from __future__ import annotations

from pathlib import Path

from skillify.agent.shogun.config_gen import generate_config


def test_no_secret_in_any_generated_artifact(tmp_path: Path) -> None:
    install = tmp_path / "bundle"
    install.mkdir()
    entrypoint = install / "shutsujin_departure.sh"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    generated = generate_config(
        install_root=install,
        run_dir=tmp_path / "run",
        preferred_cli="claude-code",
        worker_count=1,
        model="model",
        credential_refs={"ANTHROPIC_API_KEY": "vault://model/current"},
        endpoint_environment={"ANTHROPIC_BASE_URL": "https://model.internal"},
    )

    combined = "\n".join((
        generated.settings_path.read_text(encoding="utf-8"),
        generated.permissions_path.read_text(encoding="utf-8"),
        repr(generated.environment),
        repr(generated.command),
    ))
    assert "unit-test-secret-value" not in combined
    assert "vault://model/current" in combined
