from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from skillify.apps.runner import AgentAppRunner
from skillify.tasks.protocol import TaskEnvelope


NOW = datetime(2026, 7, 21, 12, tzinfo=timezone.utc)


class Outbox:
    def __init__(self):
        self.payloads = []

    def enqueue(self, event_id, payload):
        self.payloads.append(payload)
        return True


def envelope(workflow_id: str, alias: str, parameters: dict) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=f"task-{workflow_id}", endpoint_id="endpoint-1",
        workflow_id=workflow_id, workflow_version="1.0.0", workspace_alias=alias,
        parameters=parameters, issued_at=NOW, expires_at=NOW + timedelta(minutes=5),
        nonce="nonce-1", runtime="opencode", state_version=1,
    ).sign(b"secret")


def test_local_document_app_runs_fixed_contract_and_emits_structured_result(
    monkeypatch, tmp_path: Path,
) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "guide.md").write_text("Skillify local search\n", encoding="utf-8")
    outbox = Outbox()
    monkeypatch.setattr("skillify.apps.runner.ensure_venv", lambda path: path / "bin/python")
    monkeypatch.setattr("skillify.apps.runner.install_python_deps", lambda *args, **kwargs: None)
    runner = AgentAppRunner(
        {"documents": str(documents)}, outbox, state_root=tmp_path / "state",
        devpi_index_url="http://devpi.internal/root/skillify/+simple/", clock=lambda: NOW,
    )

    next_version = runner.run(envelope("local-doc-search", "documents", {
        "directoryAlias": "documents", "query": "Skillify", "mode": "fulltext",
    }), state_version=2)

    assert next_version == 4
    assert [item["eventType"] for item in outbox.payloads] == ["task.started", "task.succeeded"]
    result = outbox.payloads[-1]["artifacts"][0]["result"]
    assert result["matches"][0]["path"] == "guide.md"


def test_local_document_app_uses_separately_confirmed_alias(
    monkeypatch, tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"; workspace.mkdir()
    documents = tmp_path / "documents"; documents.mkdir()
    (documents / "guide.md").write_text("expanded scope\n", encoding="utf-8")
    outbox = Outbox()
    monkeypatch.setattr("skillify.apps.runner.ensure_venv", lambda path: path / "bin/python")
    monkeypatch.setattr("skillify.apps.runner.install_python_deps", lambda *args, **kwargs: None)
    runner = AgentAppRunner(
        {"workspace": str(workspace), "documents": str(documents)}, outbox,
        state_root=tmp_path / "state", devpi_index_url=None, clock=lambda: NOW,
    )

    runner.run(envelope("local-doc-search", "workspace", {
        "directoryAlias": "documents", "query": "expanded", "mode": "fulltext",
    }), state_version=2)

    assert outbox.payloads[-1]["eventType"] == "task.succeeded"
    assert outbox.payloads[-1]["artifacts"][0]["result"]["matches"][0]["path"] == "guide.md"


def test_file_processing_app_creates_new_output_and_never_overwrites_source(
    monkeypatch, tmp_path: Path,
) -> None:
    source = tmp_path / "input.txt"
    source.write_text("red blue red\n", encoding="utf-8")
    original = source.read_bytes()
    outbox = Outbox()
    monkeypatch.setattr("skillify.apps.runner.ensure_venv", lambda path: path / "bin/python")
    monkeypatch.setattr("skillify.apps.runner.install_python_deps", lambda *args, **kwargs: None)
    runner = AgentAppRunner(
        {"input": str(source)}, outbox, state_root=tmp_path / "state",
        devpi_index_url="http://devpi.internal/root/skillify/+simple/", clock=lambda: NOW,
    )

    runner.run(envelope("file-processing", "input", {
        "inputAlias": "input", "processor": "word-frequency",
    }), state_version=2)

    assert source.read_bytes() == original
    result = outbox.payloads[-1]["artifacts"][0]["result"]
    assert result["changes"][0]["operation"] == "created"
    assert (tmp_path / "state/outputs/task-file-processing/word-frequency.csv").is_file()
