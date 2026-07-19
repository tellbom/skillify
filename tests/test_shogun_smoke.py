"""Test-environment entry point for the approved Shogun bundle; skipped in development."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from skillify.agent.shogun.distribution import (
    check_bundle_layout, check_host_dependencies, load_manifest, require_installable,
    verify_artifact,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("SKILLIFY_TEST_SHOGUN_TEAM") != "1",
    reason="requires the real Linux Shogun/OpenCode/Claude test environment",
)


@pytest.mark.parametrize("preferred_cli", ["opencode", "claude-code"])
def test_approved_shogun_bundle_and_host_are_ready(preferred_cli: str) -> None:
    manifest_path = Path(os.environ["SKILLIFY_SHOGUN_MANIFEST_PATH"])
    artifact_path = Path(os.environ["SKILLIFY_SHOGUN_ARTIFACT_PATH"])
    install_root = Path(os.environ["SKILLIFY_SHOGUN_INSTALL_ROOT"])
    manifest = load_manifest(manifest_path)
    require_installable(manifest)
    verify_artifact(artifact_path, manifest)
    check_bundle_layout(install_root, manifest)
    status = check_host_dependencies(preferred_cli)
    assert status.available, status.detail
