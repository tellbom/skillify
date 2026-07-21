"""Endpoint-local execution for the two fixed non-technical Agent Apps."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from skillify.apps import load_bundled_app_contract
from skillify.apps.file_processing import process_text, summarize_csv
from skillify.apps.local_doc_search import DirectoryAliases, LocalDocumentSearch
from skillify.install.venv import ensure_venv, install_python_deps
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import build_task_event


APP_WORKFLOWS = frozenset({"local-doc-search", "file-processing"})


class AppEventOutbox(Protocol):
    def enqueue(self, event_id: str, payload: dict) -> bool: ...


class AgentAppRunner:
    def __init__(
        self, aliases: Mapping[str, str], outbox: AppEventOutbox, *, state_root: Path,
        devpi_index_url: str | None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.aliases = dict(aliases)
        self.outbox = outbox
        self.state_root = Path(state_root)
        self.devpi_index_url = devpi_index_url
        self.clock = clock

    def _event(self, envelope: TaskEnvelope, state_version: int, event_type: str, **extra) -> None:
        event_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"skillify:{envelope.task_id}:{event_type}:{state_version}",
        ).hex
        payload = build_task_event(
            event_id=event_id, task_id=envelope.task_id, event_type=event_type,
            occurred_at=self.clock(), workflow_id=envelope.workflow_id,
            workflow_version=envelope.workflow_version, provider="skillify-app",
            provider_version="1.0.0", nonce=envelope.nonce, state_version=state_version,
            reason_code=extra.get("reason_code"),
        )
        if "result" in extra:
            payload["artifacts"] = [{
                "kind": "app-result", "artifactId": envelope.task_id,
                "result": extra["result"],
            }]
        self.outbox.enqueue(event_id, payload)

    def _prepare_runtime(self, app_id: str) -> None:
        requirements_path = Path(__file__).resolve().parents[3] / "apps" / app_id / "requirements.lock"
        requirements = []
        if requirements_path.is_file():
            requirements = [
                line.strip() for line in requirements_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        venv = self.state_root / "venvs" / app_id
        ensure_venv(venv)
        install_python_deps(venv, requirements, index_url=self.devpi_index_url)

    def run(self, envelope: TaskEnvelope, *, state_version: int) -> int:
        contract = load_bundled_app_contract(envelope.workflow_id)
        inputs = dict(envelope.parameters)
        contract.validate_input(inputs)
        self._event(envelope, state_version, "task.started")
        version = state_version + 1
        try:
            self._prepare_runtime(envelope.workflow_id)
            if envelope.workflow_id == "local-doc-search":
                alias = str(inputs["directoryAlias"])
                if alias not in self.aliases:
                    raise PermissionError("confirmed directory alias is not configured locally")
                directories = DirectoryAliases()
                directories.register(alias, Path(self.aliases[alias]))
                result = {"matches": [item.as_dict() for item in LocalDocumentSearch(
                    directories,
                ).search(alias, str(inputs["query"]), mode=str(inputs["mode"]))]}
            else:
                alias = str(inputs["inputAlias"])
                if alias not in self.aliases:
                    raise PermissionError("confirmed input alias is not configured locally")
                source = Path(self.aliases[alias]).resolve(strict=True)
                output = self.state_root / "outputs" / envelope.task_id
                if inputs["processor"] == "word-frequency":
                    changes = process_text(source, output)
                else:
                    changes = summarize_csv(
                        source, output, group_by=str(inputs["groupBy"]),
                        value_column=str(inputs["valueColumn"]), operation=str(inputs["operation"]),
                    )
                result = {"outputAlias": envelope.task_id, "changes": changes["changes"]}
            contract.validate_output(result)
        except Exception:
            self._event(envelope, version, "task.failed", reason_code="app-execution-failed")
            return version + 1
        self._event(envelope, version, "task.succeeded", result=result)
        return version + 1
