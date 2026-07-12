from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from skillify.common.config import load_config
from skillify.web.app import app
from skillify.web.build_models import BuildNotFound, BuildRevisionConflict, BuildStateConflict
from skillify.web.build_preview import build_preview
from skillify.web.build_store import BuildStore
from tests.fake_forgejo import fake_forgejo  # noqa: F401
from tests.fake_keycloak import fake_keycloak  # noqa: F401

client = TestClient(app)


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


def test_build_store_rejects_a_concurrent_operation_lock(tmp_path: Path) -> None:
    store = BuildStore(tmp_path, ttl_seconds=60)
    record = store.create("jane", "guided")
    (record.workspace.parents[1] / ".operation.lock").write_text("busy", encoding="utf-8")

    with pytest.raises(BuildStateConflict, match="another operation"):
        store.mutate(record.build_id, "jane", 1, lambda _workspace, _meta: None)


def test_failed_mutation_preserves_revision_and_previewed_bytes(tmp_path: Path) -> None:
    store = BuildStore(tmp_path, ttl_seconds=60)
    record = store.create("jane", "guided")
    (record.workspace / "SKILL.md").write_text("original", encoding="utf-8")

    def fail_after_write(workspace: Path, _metadata: dict) -> None:
        (workspace / "SKILL.md").write_text("changed", encoding="utf-8")
        raise OSError("injected write failure")

    with pytest.raises(OSError, match="injected"):
        store.mutate(record.build_id, "jane", 1, fail_after_write)

    unchanged = store.load(record.build_id, "jane")
    assert unchanged.revision == 1
    assert (unchanged.workspace / "SKILL.md").read_text(encoding="utf-8") == "original"


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


def _configure_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_keycloak) -> str:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")
    return fake_keycloak.mint_token(audience="skillify-web", subject="jane")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_guided_build_can_be_partial_then_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure_api(monkeypatch, tmp_path, fake_keycloak)
    created = client.post(
        "/api/skill-builds/guided",
        json={"manifest": {"name": "hello-skill"}, "skillMd": "# Draft"},
        headers=_headers(token),
    )

    assert created.status_code == 200, created.text
    preview = created.json()
    assert preview["sourceType"] == "guided"
    assert "namespace" in preview["missingFields"]
    assert preview["publishable"] is False

    updated = client.patch(
        f"/api/skill-builds/{preview['buildId']}",
        json={
            "expectedRevision": preview["revision"],
            "manifest": VALID_MANIFEST,
            "skillMd": VALID_SKILL_MD,
        },
        headers=_headers(token),
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == preview["revision"] + 1
    assert updated.json()["publishable"] is True


def test_guided_update_rejects_stale_revision_and_hides_other_users_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    jane = _configure_api(monkeypatch, tmp_path, fake_keycloak)
    bob = fake_keycloak.mint_token(audience="skillify-web", subject="bob")
    preview = client.post(
        "/api/skill-builds/guided",
        json={"manifest": {}, "skillMd": ""},
        headers=_headers(jane),
    ).json()

    first = client.patch(
        f"/api/skill-builds/{preview['buildId']}",
        json={"expectedRevision": 1, "manifest": {"name": "hello-skill"}},
        headers=_headers(jane),
    )
    assert first.status_code == 200

    stale = client.patch(
        f"/api/skill-builds/{preview['buildId']}",
        json={"expectedRevision": 1, "manifest": {"version": "1.0.0"}},
        headers=_headers(jane),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["currentRevision"] == 2

    hidden = client.get(
        f"/api/skill-builds/{preview['buildId']}",
        headers=_headers(bob),
    )
    assert hidden.status_code == 404


def test_guided_file_mutation_is_revisioned_and_rejects_reserved_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure_api(monkeypatch, tmp_path, fake_keycloak)
    preview = client.post(
        "/api/skill-builds/guided",
        json={"manifest": VALID_MANIFEST, "skillMd": VALID_SKILL_MD},
        headers=_headers(token),
    ).json()

    added = client.post(
        f"/api/skill-builds/{preview['buildId']}/files",
        data={"path": "scripts/run.py", "expectedRevision": preview["revision"]},
        files={"file": ("run.py", b"print('ok')\n", "text/x-python")},
        headers=_headers(token),
    )
    assert added.status_code == 200, added.text
    added_preview = added.json()
    assert added_preview["revision"] == preview["revision"] + 1
    assert any(item["path"] == "scripts/run.py" for item in added_preview["tree"])

    rejected = client.post(
        f"/api/skill-builds/{preview['buildId']}/files",
        data={"path": "skill.yaml", "expectedRevision": added_preview["revision"]},
        files={"file": ("skill.yaml", b"bad", "text/yaml")},
        headers=_headers(token),
    )
    assert rejected.status_code == 400

    traversal = client.post(
        f"/api/skill-builds/{preview['buildId']}/files",
        data={"path": "../escape.py", "expectedRevision": added_preview["revision"]},
        files={"file": ("escape.py", b"bad", "text/x-python")},
        headers=_headers(token),
    )
    assert traversal.status_code == 400

    deleted = client.delete(
        f"/api/skill-builds/{preview['buildId']}/files",
        params={"path": "scripts/run.py", "expectedRevision": added_preview["revision"]},
        headers=_headers(token),
    )
    assert deleted.status_code == 200, deleted.text
    assert not any(item["path"] == "scripts/run.py" for item in deleted.json()["tree"])


def test_staged_content_limits_return_payload_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure_api(monkeypatch, tmp_path, fake_keycloak)
    preview = client.post(
        "/api/skill-builds/guided",
        json={"manifest": VALID_MANIFEST, "skillMd": VALID_SKILL_MD},
        headers=_headers(token),
    ).json()
    monkeypatch.setenv("SKILLIFY_MAX_EXTRACTED_BYTES", "1024")

    oversized_file = client.post(
        f"/api/skill-builds/{preview['buildId']}/files",
        data={"path": "resources/large.bin", "expectedRevision": preview["revision"]},
        files={"file": ("large.bin", b"x" * 2048, "application/octet-stream")},
        headers=_headers(token),
    )
    assert oversized_file.status_code == 413

    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "second-home"))
    oversized_guided = client.post(
        "/api/skill-builds/guided",
        json={"manifest": {}, "skillMd": "x" * 2048},
        headers=_headers(token),
    )
    assert oversized_guided.status_code == 413


def test_guided_publish_requires_confirmation_and_current_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_forgejo, fake_keycloak
) -> None:
    token = _configure_api(monkeypatch, tmp_path, fake_keycloak)
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", f"sqlite:///{(tmp_path / 'index.db').as_posix()}")
    preview = client.post(
        "/api/skill-builds/guided",
        json={"manifest": VALID_MANIFEST, "skillMd": VALID_SKILL_MD},
        headers=_headers(token),
    ).json()

    unconfirmed = client.post(
        f"/api/skill-builds/{preview['buildId']}/publish",
        json={"expectedRevision": preview["revision"], "confirmed": False},
        headers=_headers(token),
    )
    assert unconfirmed.status_code == 422

    changed = client.patch(
        f"/api/skill-builds/{preview['buildId']}",
        json={"expectedRevision": preview["revision"], "manifest": {"tags": ["demo"]}},
        headers=_headers(token),
    ).json()
    stale = client.post(
        f"/api/skill-builds/{preview['buildId']}/publish",
        json={"expectedRevision": preview["revision"], "confirmed": True},
        headers=_headers(token),
    )
    assert stale.status_code == 409

    published = client.post(
        f"/api/skill-builds/{preview['buildId']}/publish",
        json={"expectedRevision": changed["revision"], "confirmed": True},
        headers=_headers(token),
    )
    assert published.status_code == 200, published.text
    assert published.json()["buildId"] == preview["buildId"]
    assert published.json()["revision"] == changed["revision"]
    assert published.json()["releaseUrl"]

    duplicate = client.post(
        f"/api/skill-builds/{preview['buildId']}/publish",
        json={"expectedRevision": changed["revision"], "confirmed": True},
        headers=_headers(token),
    )
    assert duplicate.status_code == 409

    mutation_after_publish = client.patch(
        f"/api/skill-builds/{preview['buildId']}",
        json={"expectedRevision": changed["revision"], "manifest": {"tags": ["changed"]}},
        headers=_headers(token),
    )
    assert mutation_after_publish.status_code == 409
