"""Tests for the P1-3 temporary upload-verification FastAPI entry point."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from skillify.codemap.upload_server import build_app


def _make_tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = build_app(tasks_root=tmp_path / "tasks", token="secret-token", max_upload_bytes=10_000_000)
    return TestClient(app)


def _upload(client: TestClient, tar_bytes: bytes, *, task_id="task-1", token="secret-token", sha256=None):
    sha256 = sha256 or hashlib.sha256(tar_bytes).hexdigest()
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.post(
        "/codemap/upload",
        data={"task_id": task_id, "sha256": sha256},
        files={"tar": ("snapshot.tar.gz", tar_bytes, "application/gzip")},
        headers=headers,
    )


def test_upload_extracts_to_task_source_dir(tmp_path: Path, client: TestClient) -> None:
    tar_bytes = _make_tar_bytes({"main.py": b"print(1)\n"})

    response = _upload(client, tar_bytes, task_id="task-1")

    assert response.status_code == 200
    assert response.json() == {"task_id": "task-1", "extracted_files": 1}
    assert (tmp_path / "tasks" / "task-1" / "source" / "main.py").read_bytes() == b"print(1)\n"


def test_upload_rejects_missing_token(client: TestClient) -> None:
    tar_bytes = _make_tar_bytes({"main.py": b"x\n"})
    response = _upload(client, tar_bytes, token=None)
    assert response.status_code == 401


def test_upload_rejects_wrong_token(client: TestClient) -> None:
    tar_bytes = _make_tar_bytes({"main.py": b"x\n"})
    response = _upload(client, tar_bytes, token="wrong")
    assert response.status_code == 401


def test_upload_rejects_checksum_mismatch(client: TestClient) -> None:
    tar_bytes = _make_tar_bytes({"main.py": b"x\n"})
    response = _upload(client, tar_bytes, sha256="0" * 64)
    assert response.status_code == 400
    assert "checksum" in response.json()["detail"]


def test_upload_rejects_invalid_task_id(client: TestClient) -> None:
    tar_bytes = _make_tar_bytes({"main.py": b"x\n"})
    response = _upload(client, tar_bytes, task_id="../escape")
    assert response.status_code == 400


def test_upload_rejects_oversized_payload(tmp_path: Path) -> None:
    app = build_app(tasks_root=tmp_path / "tasks", token="secret-token", max_upload_bytes=10)
    client = TestClient(app)
    tar_bytes = _make_tar_bytes({"main.py": b"x" * 1000})

    response = _upload(client, tar_bytes)

    assert response.status_code == 413


def test_upload_rejects_path_traversal_member(client: TestClient) -> None:
    tar_bytes = _make_tar_bytes({"../../etc/passwd": b"pwned\n"})
    response = _upload(client, tar_bytes)
    assert response.status_code == 400
