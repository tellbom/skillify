from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from skillify.common.config import load_config
from skillify.web.build_models import BuildNotFound, BuildRevisionConflict
from skillify.web.build_preview import build_preview
from skillify.web.build_store import BuildStore


VALID_MANIFEST = {
    "manifestVersion": 1,
    "namespace": "demo",
    "name": "hello-skill",
    "version": "1.0.0",
    "description": "Say hello.",
    "author": "jane",
    "license": "MIT",
    "runtime": "claude-agent-skill",
    "targets": ["claude"],
}

VALID_SKILL_MD = """---
name: hello-skill
description: Say hello.
---

# Hello
"""


def test_build_ttl_defaults_and_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path))
    assert load_config().build_ttl_seconds == 86400

    monkeypatch.setenv("SKILLIFY_BUILD_TTL_SECONDS", "60")
    assert load_config().build_ttl_seconds == 60


def test_build_store_is_owner_bound_revisioned_and_expiring(tmp_path: Path) -> None:
    current = [datetime(2026, 7, 12, tzinfo=timezone.utc)]
    store = BuildStore(tmp_path, ttl_seconds=60, clock=lambda: current[0])
    record = store.create("jane", "guided")

    assert record.revision == 1
    assert record.owner == "jane"
    assert record.workspace.is_dir()

    with pytest.raises(BuildNotFound):
        store.load(record.build_id, "bob")

    updated = store.mutate(record.build_id, "jane", 1, lambda _workspace, _meta: None)
    assert updated.revision == 2

    with pytest.raises(BuildRevisionConflict) as exc_info:
        store.mutate(record.build_id, "jane", 1, lambda _workspace, _meta: None)
    assert exc_info.value.current_revision == 2

    current[0] += timedelta(seconds=61)
    with pytest.raises(BuildNotFound):
        store.load(record.build_id, "jane")
    assert not record.workspace.parent.exists()


def test_build_preview_reports_exact_native_content_and_validation(tmp_path: Path) -> None:
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    store = BuildStore(tmp_path, ttl_seconds=60, clock=lambda: now)
    record = store.create("jane", "guided")
    manifest_yaml = yaml.safe_dump(VALID_MANIFEST, sort_keys=False, allow_unicode=True)
    (record.workspace / "skill.yaml").write_text(manifest_yaml, encoding="utf-8")
    (record.workspace / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")
    (record.workspace / "scripts").mkdir()
    (record.workspace / "scripts" / "run.py").write_text("print('hello')\n", encoding="utf-8")

    preview = build_preview(store.load(record.build_id, "jane"))

    assert preview["buildId"] == record.build_id
    assert preview["manifest"] == VALID_MANIFEST
    assert preview["manifestYaml"] == manifest_yaml
    assert preview["skillMd"] == VALID_SKILL_MD
    assert preview["missingFields"] == []
    assert preview["issues"] == []
    assert preview["publishable"] is True
    assert preview["status"] == "ready"
    assert [item["path"] for item in preview["tree"]] == [
        "SKILL.md",
        "scripts",
        "scripts/run.py",
        "skill.yaml",
    ]


def test_external_preview_separates_missing_and_unconfirmed_fields(tmp_path: Path) -> None:
    store = BuildStore(tmp_path, ttl_seconds=60)
    record = store.create(
        "jane",
        "external",
        detected_facts={"frontmatter": {"name": "hello-skill", "description": "Say hello."}},
    )
    (record.workspace / "skill.yaml").write_text(
        yaml.safe_dump(
            {"manifestVersion": 1, "name": "hello-skill", "description": "Say hello."},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (record.workspace / "SKILL.md").write_text(VALID_SKILL_MD, encoding="utf-8")

    preview = build_preview(record)

    assert "namespace" in preview["missingFields"]
    assert "version" in preview["missingFields"]
    assert "dependencies" in preview["missingFields"]
    assert "permissions" in preview["missingFields"]
    assert "tags" in preview["missingFields"]
    assert preview["unconfirmedFields"] == ["description", "name"]
    assert preview["publishable"] is False
