"""End-to-end T2.2 acceptance check: "新发布后 Web/搜索可查" — after a publish (via the
webhook pipeline, T2.1), the Postgres-shaped index is queryable and has the new entry.
"""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from skillify.index.db import make_engine, session_scope
from skillify.index.queries import list_latest, search
from skillify.webhook.app import app
from tests.fake_forgejo import fake_forgejo  # noqa: F401

client = TestClient(app)

_MANIFEST_YAML = (
    "manifestVersion: 1\nnamespace: excel\nname: pivot-analysis\nversion: 0.1.0\n"
    "description: Build pivot tables from tabular data.\nauthor: Jane Doe\nlicense: MIT\n"
    "runtime: claude-agent-skill\ntargets: [claude]\ntags: [excel, data]\n"
)


def _archive_bytes() -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            files = {
                "SKILL.md": b"---\nname: pivot-analysis\ndescription: x\n---\nbody\n",
                "skill.yaml": _MANIFEST_YAML.encode(),
            }
            for name, content in files.items():
                info = tarfile.TarInfo(name=f"pivot-analysis-src/{name}")
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_publish_via_webhook_makes_skill_searchable_in_index(tmp_path: Path, monkeypatch, fake_forgejo) -> None:
    monkeypatch.setenv("SKILLIFY_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SKILLIFY_FORGEJO_URL", f"http://127.0.0.1:{fake_forgejo.server_port}")
    monkeypatch.setenv("SKILLIFY_FORGEJO_TOKEN", "tok")
    index_db_url = f"sqlite:///{(tmp_path / 'index.db').as_posix()}"
    monkeypatch.setenv("SKILLIFY_INDEX_DB_URL", index_db_url)
    fake_forgejo.state.archives["excel/pivot-analysis/v0.1.0"] = _archive_bytes()

    resp = client.post(
        "/webhook/forgejo",
        json={"ref": "refs/tags/v0.1.0", "repository": {"name": "pivot-analysis", "owner": {"username": "excel"}}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "published"
    assert body["indexError"] is None

    engine = make_engine(index_db_url)
    with session_scope(engine) as session:
        latest = list_latest(session)
        assert len(latest) == 1
        entry = latest[0]
        assert entry.namespace == "excel"
        assert entry.name == "pivot-analysis"
        assert entry.version == "0.1.0"
        assert entry.tags == ["excel", "data"]
        assert entry.checksum
        assert entry.release_url

        results, total = search(session, "pivot")
        assert [e.name for e in results] == ["pivot-analysis"]
        assert total == 1
