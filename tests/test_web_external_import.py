from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.web.app import app
from tests.fake_keycloak import fake_keycloak  # noqa: F401

client = TestClient(app)


def _zip(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fake_keycloak) -> str:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_REALM_URL", fake_keycloak.realm_url)
    monkeypatch.setenv("SKILLIFY_KEYCLOAK_AUDIENCE", "skillify-web")
    return fake_keycloak.mint_token(audience="skillify-web", subject="jane")


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _multi_skill_zip() -> bytes:
    return _zip(
        {
            "bundle/alpha/SKILL.md": (
                "---\nname: alpha\ndescription: Alpha skill.\n---\n\n# Alpha\n"
            ),
            "bundle/alpha/scripts/run.py": "print('alpha')\n",
            "bundle/alpha/requirements.txt": "requests>=2.31\n# comment\n\npyyaml>=6\n",
            "bundle/beta/SKILL.md": (
                "---\nname: Beta Skill\ndescription: Beta skill.\n---\n\n# Beta\n"
            ),
            "bundle/beta/assets/icon.txt": "icon",
            "bundle/beta/package.json": '{"dependencies":{"left-pad":"1.3.0"}}',
        }
    )


def test_external_scan_reports_multiple_candidates_and_only_explicit_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure(monkeypatch, tmp_path, fake_keycloak)
    response = client.post(
        "/api/external-skill-scans",
        files={"file": ("skills.zip", _multi_skill_zip(), "application/zip")},
        headers=_headers(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scanId"]
    candidates = body["candidates"]
    assert [candidate["rootPath"] for candidate in candidates] == ["bundle/alpha", "bundle/beta"]

    alpha, beta = candidates
    assert alpha["frontmatter"] == {"name": "alpha", "description": "Alpha skill."}
    assert alpha["detectedPaths"] == ["requirements.txt", "scripts"]
    assert alpha["pythonRequirements"] == ["requests>=2.31", "pyyaml>=6"]
    assert "namespace" not in alpha["frontmatter"]
    assert "version" not in alpha["frontmatter"]
    assert beta["frontmatter"]["name"] == "Beta Skill"
    assert beta["detectedPaths"] == ["assets", "package.json"]
    assert beta["pythonRequirements"] == []


def test_external_selection_creates_independent_unconfirmed_builds_without_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure(monkeypatch, tmp_path, fake_keycloak)
    scan = client.post(
        "/api/external-skill-scans",
        files={"file": ("skills.zip", _multi_skill_zip(), "application/zip")},
        headers=_headers(token),
    ).json()

    selected = client.post(
        f"/api/external-skill-scans/{scan['scanId']}/selections",
        json={"candidateIds": [candidate["candidateId"] for candidate in scan["candidates"]]},
        headers=_headers(token),
    )

    assert selected.status_code == 200, selected.text
    builds = selected.json()["builds"]
    assert len(builds) == 2
    alpha, beta = builds
    assert alpha["buildId"] != beta["buildId"]
    assert alpha["manifest"]["name"] == "alpha"
    assert alpha["manifest"]["description"] == "Alpha skill."
    assert alpha["manifest"]["dependencies"]["python"] == ["requests>=2.31", "pyyaml>=6"]
    assert "namespace" not in alpha["manifest"]
    assert "version" not in alpha["manifest"]
    assert "author" not in alpha["manifest"]
    assert "license" not in alpha["manifest"]
    assert "permissions" not in alpha["manifest"]
    assert "tags" not in alpha["manifest"]
    assert "namespace" in alpha["missingFields"]
    assert "permissions" in alpha["missingFields"]
    assert alpha["unconfirmedFields"] == ["dependencies", "description", "name"]
    assert alpha["publishable"] is False

    # Invalid external names are preserved for explicit correction, never slugified.
    assert beta["manifest"]["name"] == "Beta Skill"
    assert any("name" in issue["path"] for issue in beta["issues"])


def test_external_build_becomes_publishable_only_after_complete_explicit_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure(monkeypatch, tmp_path, fake_keycloak)
    scan = client.post(
        "/api/external-skill-scans",
        files={"file": ("skill.zip", _multi_skill_zip(), "application/zip")},
        headers=_headers(token),
    ).json()
    selected = client.post(
        f"/api/external-skill-scans/{scan['scanId']}/selections",
        json={"candidateIds": [scan["candidates"][0]["candidateId"]]},
        headers=_headers(token),
    ).json()["builds"][0]

    complete_manifest = {
        "namespace": "demo",
        "name": "alpha",
        "version": "1.0.0",
        "description": "Alpha skill.",
        "author": "jane",
        "license": "MIT",
        "runtime": "claude-agent-skill",
        "targets": ["claude"],
        "dependencies": {"python": ["requests>=2.31", "pyyaml>=6"], "system": [], "skills": []},
        "permissions": [],
        "tags": [],
    }
    updated = client.patch(
        f"/api/skill-builds/{selected['buildId']}",
        json={"expectedRevision": selected["revision"], "manifest": complete_manifest},
        headers=_headers(token),
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["missingFields"] == []
    assert updated.json()["unconfirmedFields"] == []
    assert updated.json()["publishable"] is True


def test_external_scan_reports_malformed_frontmatter_and_rejects_no_skill_md(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure(monkeypatch, tmp_path, fake_keycloak)
    malformed = client.post(
        "/api/external-skill-scans",
        files={"file": ("bad.zip", _zip({"bad/SKILL.md": "---\nname: [\n---\n"}), "application/zip")},
        headers=_headers(token),
    )
    assert malformed.status_code == 200
    candidate = malformed.json()["candidates"][0]
    assert candidate["frontmatter"] == {}
    assert candidate["issues"][0]["path"] == "SKILL.md:frontmatter"

    empty = client.post(
        "/api/external-skill-scans",
        files={"file": ("empty.zip", _zip({"README.md": "none"}), "application/zip")},
        headers=_headers(token),
    )
    assert empty.status_code == 422


def test_external_scan_selection_is_owner_bound_and_validates_candidate_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    jane = _configure(monkeypatch, tmp_path, fake_keycloak)
    bob = fake_keycloak.mint_token(audience="skillify-web", subject="bob")
    scan = client.post(
        "/api/external-skill-scans",
        files={"file": ("skills.zip", _multi_skill_zip(), "application/zip")},
        headers=_headers(jane),
    ).json()

    hidden = client.post(
        f"/api/external-skill-scans/{scan['scanId']}/selections",
        json={"candidateIds": [scan["candidates"][0]["candidateId"]]},
        headers=_headers(bob),
    )
    assert hidden.status_code == 404

    duplicate = client.post(
        f"/api/external-skill-scans/{scan['scanId']}/selections",
        json={"candidateIds": [scan["candidates"][0]["candidateId"]] * 2},
        headers=_headers(jane),
    )
    assert duplicate.status_code == 400


def test_external_scan_reads_only_explicit_pyproject_project_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_keycloak
) -> None:
    token = _configure(monkeypatch, tmp_path, fake_keycloak)
    archive = _zip(
        {
            "skill/SKILL.md": "---\nname: toml-skill\ndescription: TOML skill.\n---\n",
            "skill/pyproject.toml": (
                "[project]\nname = 'unrelated-package-name'\n"
                "dependencies = ['httpx>=0.27', 'PyYAML>=6']\n"
                "[tool.example]\ndependency = 'must-not-be-read'\n"
            ),
        }
    )
    response = client.post(
        "/api/external-skill-scans",
        files={"file": ("skill.zip", archive, "application/zip")},
        headers=_headers(token),
    )

    assert response.status_code == 200, response.text
    candidate = response.json()["candidates"][0]
    assert candidate["detectedPaths"] == ["pyproject.toml"]
    assert candidate["pythonRequirements"] == ["httpx>=0.27", "PyYAML>=6"]
