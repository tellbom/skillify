"""Bridge task runner for fixed Code Map visualization actions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from skillify.codemap.visualizer import CODEMAP_WORKFLOWS, CodemapError, GitNexusVisualizer
from skillify.tasks.protocol import TaskEnvelope
from skillify.tasks.reporting import build_task_event


class EventOutbox(Protocol):
    def enqueue(self, event_id: str, payload: dict) -> bool: ...


class CodemapTaskRunner:
    def __init__(
        self,
        visualizer: GitNexusVisualizer,
        workspace_resolver: Callable[[str], Path],
        outbox: EventOutbox,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.visualizer = visualizer
        self.workspace_resolver = workspace_resolver
        self.outbox = outbox
        self.clock = clock

    def run(self, envelope: TaskEnvelope, *, state_version: int) -> int:
        if envelope.workflow_id not in CODEMAP_WORKFLOWS:
            raise CodemapError("unsupported Code Map action")
        action = envelope.workflow_id.rsplit(".", 1)[-1]
        version = state_version
        sequence = 0

        def emit(event_type: str, summary: str, reason: str | None = None) -> None:
            nonlocal version, sequence
            event_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"skillify:{envelope.task_id}:gitnexus:{event_type}:{sequence}",
            ).hex
            self.outbox.enqueue(event_id, build_task_event(
                event_id=event_id, task_id=envelope.task_id, event_type=event_type,
                occurred_at=self.clock(), workflow_id=envelope.workflow_id,
                workflow_version=envelope.workflow_version, provider="gitnexus",
                provider_version=self.visualizer.manifest.version, reason_code=reason,
                nonce=envelope.nonce, state_version=version, summary=summary,
            ))
            version += 1
            sequence += 1

        emit("codemap.visualization.requested", f"Code Map {action} requested")
        try:
            if action == "start":
                emit("codemap.visualization.scan_started", "Creating a read-only workspace snapshot")
                workspace = self.workspace_resolver(envelope.workspace_alias)
                status = self.visualizer.start(envelope.workspace_alias, workspace)
                emit("codemap.visualization.scan_completed", "GitNexus index completed")
                emit("codemap.visualization.started", "GitNexus localhost service started")
                emit("codemap.visualization.ready", status.detail)
            elif action == "stop":
                status = self.visualizer.stop(envelope.workspace_alias)
                emit("codemap.visualization.stopped", status.detail)
            elif action == "open":
                status = self.visualizer.open(envelope.workspace_alias)
                emit("codemap.visualization.opened", status.detail)
            else:
                status = self.visualizer.status(envelope.workspace_alias)
                emit("codemap.visualization.status", status.detail)
        except CodemapError as exc:
            reason = "BROWSER_BLOCKED" if "Chrome" in str(exc) else "CODEMAP_FAILED"
            event_type = (
                "codemap.visualization.browser_blocked"
                if reason == "BROWSER_BLOCKED" else "codemap.visualization.failed"
            )
            emit(event_type, str(exc), reason)
        return version
