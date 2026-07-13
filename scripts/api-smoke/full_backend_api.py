"""Real-environment Skillify backend smoke/E2E test (credentials via environment only)."""
from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile

import requests

BASE = os.environ["SKILLIFY_TEST_BASE_URL"].rstrip("/")
TOKEN_URL = os.environ["SKILLIFY_TEST_TOKEN_URL"]
CLIENT = os.getenv("SKILLIFY_TEST_CLIENT_ID", "skillify-web")


def token(user_key: str, pass_key: str) -> str:
    response = requests.post(TOKEN_URL, data={"client_id": CLIENT, "grant_type": "password", "username": os.environ[user_key], "password": os.environ[pass_key]}, timeout=20)
    response.raise_for_status()
    return response.json()["access_token"]


def zip_bytes(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return out.getvalue()


results: list[dict] = []


def check(name: str, response: requests.Response, expected: int | tuple[int, ...]) -> dict:
    expected_set = (expected,) if isinstance(expected, int) else expected
    ok = response.status_code in expected_set
    results.append({"name": name, "status": response.status_code, "passed": ok})
    if not ok:
        raise AssertionError(f"{name}: expected {expected_set}, got {response.status_code}: {response.text[:1000]}")
    return response.json() if response.content else {}


def main() -> None:
    stamp = str(int(time.time()))
    first, second = token("SKILLIFY_TEST_USERNAME", "SKILLIFY_TEST_PASSWORD"), token("SKILLIFY_TEST_SECOND_USERNAME", "SKILLIFY_TEST_SECOND_PASSWORD")
    h1, h2 = {"Authorization": f"Bearer {first}"}, {"Authorization": f"Bearer {second}"}
    check("health", requests.get(f"{BASE}/healthz", timeout=20), 200)
    check("auth.valid", requests.get(f"{BASE}/api/skills", headers=h1, timeout=20), 200)
    check("auth.missing", requests.get(f"{BASE}/api/skills", timeout=20), 401)
    check("auth.invalid", requests.get(f"{BASE}/api/skills", headers={"Authorization": "Bearer invalid.token"}, timeout=20), 401)

    guided_name = f"guided-{stamp}"
    manifest = {"manifestVersion": 1, "namespace": f"e2e-{stamp}", "name": guided_name, "version": "1.0.0", "description": "Real guided test", "author": os.environ["SKILLIFY_TEST_USERNAME"], "license": "MIT", "runtime": "claude-agent-skill", "targets": ["claude"], "dependencies": {"python": [], "system": [], "skills": []}, "permissions": [], "tags": ["e2e"]}
    skill_md = f"---\nname: {guided_name}\ndescription: Real guided test\n---\n\n# Guided\n"
    partial = check("guided.partial", requests.post(f"{BASE}/api/skill-builds/guided", headers=h1, json={"manifest": {"name": "guided"}, "skillMd": "# draft"}, timeout=20), 200)
    patched = check("guided.patch", requests.patch(f"{BASE}/api/skill-builds/{partial['buildId']}", headers=h1, json={"expectedRevision": partial["revision"], "manifest": manifest, "skillMd": skill_md}, timeout=20), 200)
    check("guided.owner_isolation", requests.get(f"{BASE}/api/skill-builds/{partial['buildId']}", headers=h2, timeout=20), 404)
    added = check("guided.file_add", requests.post(f"{BASE}/api/skill-builds/{partial['buildId']}/files", headers=h1, data={"path": "scripts/run.py", "expectedRevision": patched["revision"]}, files={"file": ("run.py", b"print('ok')\n")}, timeout=20), 200)
    check("guided.path_traversal", requests.post(f"{BASE}/api/skill-builds/{partial['buildId']}/files", headers=h1, data={"path": "../bad.py", "expectedRevision": added["revision"]}, files={"file": ("bad.py", b"bad")}, timeout=20), 400)
    check("guided.stale_revision", requests.post(f"{BASE}/api/skill-builds/{partial['buildId']}/publish", headers=h1, json={"expectedRevision": patched["revision"], "confirmed": True}, timeout=60), 409)
    check("guided.unconfirmed", requests.post(f"{BASE}/api/skill-builds/{partial['buildId']}/publish", headers=h1, json={"expectedRevision": added["revision"], "confirmed": False}, timeout=60), 422)
    check("guided.publish", requests.post(f"{BASE}/api/skill-builds/{partial['buildId']}/publish", headers=h1, json={"expectedRevision": added["revision"], "confirmed": True}, timeout=120), 200)
    check("guided.repeat_publish", requests.post(f"{BASE}/api/skill-builds/{partial['buildId']}/publish", headers=h1, json={"expectedRevision": added["revision"], "confirmed": True}, timeout=60), 409)

    native_name = f"native-{stamp}"
    native_manifest = dict(manifest, name=native_name, version="1.0.0")
    native_md = skill_md.replace(guided_name, native_name).replace("Guided", "Native")
    import yaml
    archive = zip_bytes({"skill.yaml": yaml.safe_dump(native_manifest, sort_keys=False), "SKILL.md": native_md})
    native = check("native.preview", requests.post(f"{BASE}/api/skills/upload", headers=h1, files={"file": ("native.zip", archive, "application/zip")}, timeout=30), 200)
    check("native.publish", requests.post(f"{BASE}/api/skill-builds/{native['buildId']}/publish", headers=h1, json={"expectedRevision": native["revision"], "confirmed": True}, timeout=120), 200)
    duplicate = check("native.duplicate_version", requests.post(f"{BASE}/api/skills/upload", headers=h1, files={"file": ("native.zip", archive, "application/zip")}, timeout=30), 200)
    check("native.duplicate_publish", requests.post(f"{BASE}/api/skill-builds/{duplicate['buildId']}/publish", headers=h1, json={"expectedRevision": duplicate["revision"], "confirmed": True}, timeout=120), 409)

    external = zip_bytes({"bundle/alpha/SKILL.md": "---\nname: alpha\ndescription: Alpha external\n---\n\n# Alpha\n", "bundle/alpha/requirements.txt": "requests>=2.31\n", "bundle/beta/SKILL.md": "---\nname: beta\ndescription: Beta external\n---\n\n# Beta\n"})
    scan = check("external.scan", requests.post(f"{BASE}/api/external-skill-scans", headers=h1, files={"file": ("external.zip", external, "application/zip")}, timeout=30), 200)
    check("external.scan_isolation", requests.post(f"{BASE}/api/external-skill-scans/{scan['scanId']}/selections", headers=h2, json={"candidateIds": [scan['candidates'][0]['candidateId']]}, timeout=20), 404)
    selected = check("external.multi_select", requests.post(f"{BASE}/api/external-skill-scans/{scan['scanId']}/selections", headers=h1, json={"candidateIds": [c['candidateId'] for c in scan['candidates']]}, timeout=30), 200)
    check("external.repeat_select", requests.post(f"{BASE}/api/external-skill-scans/{scan['scanId']}/selections", headers=h1, json={"candidateIds": [scan['candidates'][0]['candidateId']]}, timeout=20), 400)
    ext = selected["builds"][0]
    ext_manifest = dict(manifest, name=f"alpha-{stamp}", version="1.0.0", description="Alpha external", dependencies={"python": ["requests>=2.31"], "system": [], "skills": []})
    ext_ready = check("external.confirm_fields", requests.patch(f"{BASE}/api/skill-builds/{ext['buildId']}", headers=h1, json={"expectedRevision": ext["revision"], "manifest": ext_manifest}, timeout=30), 200)
    check("external.publish", requests.post(f"{BASE}/api/skill-builds/{ext['buildId']}/publish", headers=h1, json={"expectedRevision": ext_ready["revision"], "confirmed": True}, timeout=120), 200)
    check("external.no_skill_md", requests.post(f"{BASE}/api/external-skill-scans", headers=h1, files={"file": ("empty.zip", zip_bytes({"README.md": "none"}), "application/zip")}, timeout=20), 422)
    check("search.published", requests.get(f"{BASE}/api/search", headers=h1, params={"q": "Real guided test"}, timeout=20), 200)
    check("namespace.denied", requests.post(f"{BASE}/api/skill-builds/guided", headers=h2, json={"manifest": dict(manifest, name="denied", version="1.0.0"), "skillMd": skill_md}, timeout=20), 200)
    print(json.dumps({"passed": all(r["passed"] for r in results), "count": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc), "results": results}, ensure_ascii=False, indent=2))
        sys.exit(1)
