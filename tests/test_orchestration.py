"""Tests for T6.3 — orchestration manifest field parsed + exposed (no engine implemented)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from skillify.cli.publish_cmd import run_publish
from skillify.packaging.pack import pack_skill
from skillify.web.app import app
from tests.fake_forgejo import fake_forgejo  # noqa: F401
from tests.fake_keycloak import fake_keycloak  # noqa: F401

client = TestClient(app)


class _Console:
    def print(self, *a, **k):
        pass


def _write_skill(skill_dir: Path, *, orchestration_yaml: str = "") -> None:
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: pivot-analysis\ndescription: x\n---\nbody\n", encoding="utf-8")
    (skill_dir / "skill.yaml").write_text(
        "manifestVersion: 1\nnamespace: excel\nname: pivot-analysis\nversion: 0.1.0\n"
        "description: x\nauthor: t\nlicense: MIT\nruntime: claude-agent-skill\ntargets: [claude]\n"
        f"{orchestration_yaml}",
        encoding="utf-8",
    )


def test_pack_skill_extracts_orchestration_field(tmp_path: Path) -> None:
    skill_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(skill_dir, orchestration_yaml="orchestration:\n  role: aggregator\n  dependsOn: [excel/lookup]\n")

    result = pack_skill(skill_dir, tmp_path / "dist")
    assert result.orchestration == {"role": "aggregator", "dependsOn": ["excel/lookup"]}


def test_pack_skill_defaults_orchestration_to_empty_dict(tmp_path: Path) -> None:
    skill_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(skill_dir)

    result = pack_skill(skill_dir, tmp_path / "dist")
    assert result.orchestration == {}


def test_orchestration_endpoint_returns_published_field(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    index_db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")

    skill_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(skill_dir, orchestration_yaml="orchestration:\n  role: aggregator\n  maxConcurrency: 3\n")
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())

    token = fake_keycloak.mint_token(audience="skillify-web")
    resp = client.get(
        "/api/skills/excel/pivot-analysis/orchestration", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"role": "aggregator", "maxConcurrency": 3}


def test_orchestration_endpoint_returns_empty_dict_when_unset(tmp_path: Path, monkeypatch, fake_forgejo, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    index_db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")

    skill_dir = tmp_path / "src" / "excel" / "pivot-analysis"
    _write_skill(skill_dir)
    run_publish(skill_dir=skill_dir, dry_run=False, console=_Console(), err_console=_Console())

    token = fake_keycloak.mint_token(audience="skillify-web")
    resp = client.get(
        "/api/skills/excel/pivot-analysis/orchestration", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == {}


def test_orchestration_endpoint_404_for_unknown_skill(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    index_db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")

    token = fake_keycloak.mint_token(audience="skillify-web")
    resp = client.get(
        "/api/skills/nope/nothing/orchestration", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


def test_orchestration_endpoint_requires_auth(tmp_path: Path, monkeypatch, fake_keycloak) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    index_db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")

    resp = client.get("/api/skills/nope/nothing/orchestration")
    assert resp.status_code == 401
