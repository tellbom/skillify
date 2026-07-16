"""Signed v1 endpoint task envelopes and SQLite development state store."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from skillify.agent.events import TASK_PROTOCOL_VERSION


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_FORBIDDEN_PARAMETER_KEYS = frozenset({"prompt", "shell", "command", "source", "source_code"})


class EndpointTaskState(str, Enum):
    QUEUED = "queued"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    REVOKED = "revoked"


_TRANSITIONS = {
    EndpointTaskState.QUEUED: frozenset({
        EndpointTaskState.AWAITING_CONFIRMATION, EndpointTaskState.RUNNING,
        EndpointTaskState.CANCELLED, EndpointTaskState.REJECTED, EndpointTaskState.REVOKED,
    }),
    EndpointTaskState.AWAITING_CONFIRMATION: frozenset({
        EndpointTaskState.RUNNING, EndpointTaskState.CANCELLED,
        EndpointTaskState.REJECTED, EndpointTaskState.REVOKED,
    }),
    EndpointTaskState.RUNNING: frozenset({
        EndpointTaskState.SUCCEEDED, EndpointTaskState.FAILED,
        EndpointTaskState.CANCELLED, EndpointTaskState.REVOKED,
    }),
}


class TaskProtocolError(ValueError):
    pass


class TaskReplayError(TaskProtocolError):
    pass


class TaskConflictError(TaskProtocolError):
    pass


def _utc(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise TaskProtocolError(f"{name} must be UTC-aware")


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TaskProtocolError("task parameters must be JSON serializable") from exc


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    endpoint_id: str
    workflow_id: str
    workflow_version: str
    workspace_alias: str
    parameters: Mapping[str, Any]
    issued_at: datetime
    expires_at: datetime
    nonce: str
    runtime: str = "opencode"
    mcp_packages: tuple[str, ...] = ()
    state_version: int = 0
    signature: str = ""
    task_protocol_version: int = TASK_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("task_id", self.task_id), ("endpoint_id", self.endpoint_id),
            ("workflow_id", self.workflow_id), ("nonce", self.nonce),
        ):
            if type(value) is not str or not _IDENTIFIER.fullmatch(value):
                raise TaskProtocolError(f"{name} is invalid")
        if type(self.workflow_version) is not str or not self.workflow_version:
            raise TaskProtocolError("workflow_version is required")
        if type(self.workspace_alias) is not str or not _ALIAS.fullmatch(self.workspace_alias):
            raise TaskProtocolError("workspace_alias must be a relative configured alias")
        if self.runtime not in {"opencode", "claude-code"}:
            raise TaskProtocolError("task runtime is unsupported")
        if any(type(name) is not str or not _IDENTIFIER.fullmatch(name) for name in self.mcp_packages):
            raise TaskProtocolError("task MCP package names are invalid")
        if type(self.state_version) is not int or self.state_version < 0:
            raise TaskProtocolError("state_version must be a non-negative integer")
        if type(self.parameters) not in {dict, type(MappingProxyType({}))}:
            raise TaskProtocolError("parameters must be an object")
        copied = dict(self.parameters)
        if _FORBIDDEN_PARAMETER_KEYS & {str(key).casefold() for key in copied}:
            raise TaskProtocolError("task parameters cannot contain arbitrary prompt, shell, or source")
        _canonical(copied)
        object.__setattr__(self, "parameters", MappingProxyType(copied))
        _utc(self.issued_at, "issued_at")
        _utc(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise TaskProtocolError("expires_at must be after issued_at")
        if self.task_protocol_version != TASK_PROTOCOL_VERSION:
            raise TaskProtocolError("unsupported task protocol version")
        if type(self.signature) is not str:
            raise TaskProtocolError("signature must be a string")

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "taskProtocolVersion": self.task_protocol_version,
            "taskId": self.task_id,
            "endpointId": self.endpoint_id,
            "workflowId": self.workflow_id,
            "workflowVersion": self.workflow_version,
            "workspaceAlias": self.workspace_alias,
            "parameters": dict(self.parameters),
            "issuedAt": self.issued_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "nonce": self.nonce,
            "runtime": self.runtime,
            "mcpPackages": list(self.mcp_packages),
            "stateVersion": self.state_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.unsigned_dict(), "signature": self.signature}

    def sign(self, secret: bytes) -> "TaskEnvelope":
        if not secret:
            raise TaskProtocolError("signing secret is required")
        signature = hmac.new(secret, _canonical(self.unsigned_dict()), hashlib.sha256).hexdigest()
        return replace(self, signature=signature)

    def verify(self, secret: bytes, now: datetime) -> None:
        _utc(now, "now")
        expected = self.sign(secret).signature
        if not self.signature or not hmac.compare_digest(self.signature, expected):
            raise TaskProtocolError("task signature is invalid")
        if now < self.issued_at or now >= self.expires_at:
            raise TaskProtocolError("task envelope is not currently valid")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskEnvelope":
        expected = {
            "taskProtocolVersion", "taskId", "endpointId", "workflowId",
            "workflowVersion", "workspaceAlias", "parameters", "issuedAt",
            "expiresAt", "nonce", "signature",
            "runtime", "mcpPackages", "stateVersion",
        }
        if set(value) != expected:
            raise TaskProtocolError("task envelope fields are invalid")
        try:
            return cls(
                task_id=value["taskId"], endpoint_id=value["endpointId"],
                workflow_id=value["workflowId"], workflow_version=value["workflowVersion"],
                workspace_alias=value["workspaceAlias"], parameters=value["parameters"],
                issued_at=datetime.fromisoformat(value["issuedAt"]),
                expires_at=datetime.fromisoformat(value["expiresAt"]),
                nonce=value["nonce"], signature=value["signature"],
                runtime=value["runtime"], state_version=value["stateVersion"],
                mcp_packages=tuple(value["mcpPackages"]),
                task_protocol_version=value["taskProtocolVersion"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TaskProtocolError):
                raise
            raise TaskProtocolError("task envelope values are invalid") from exc


@dataclass(frozen=True)
class StoredTask:
    task_id: str
    state: EndpointTaskState
    version: int
    revoked: bool
    envelope: TaskEnvelope = field(repr=False)


class SQLiteTaskStore:
    """SQLite implementation used by offline tests and local development."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_schema(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS endpoint_tasks (
                task_id TEXT PRIMARY KEY,
                envelope_json TEXT NOT NULL,
                state TEXT NOT NULL,
                state_version INTEGER NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS endpoint_task_nonces (
                nonce TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                accepted_at TEXT NOT NULL
            );
        """)

    def _row(self, task_id: str) -> tuple[Any, ...] | None:
        return self.connection.execute(
            "SELECT envelope_json, state, state_version, revoked FROM endpoint_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()

    def get(self, task_id: str) -> StoredTask | None:
        row = self._row(task_id)
        if row is None:
            return None
        return StoredTask(
            task_id, EndpointTaskState(row[1]), int(row[2]), bool(row[3]),
            TaskEnvelope.from_dict(json.loads(row[0])),
        )

    def accept(self, envelope: TaskEnvelope, *, secret: bytes, now: datetime) -> StoredTask:
        envelope.verify(secret, now)
        serialized = _canonical(envelope.to_dict()).decode("utf-8")
        with self.connection:
            existing = self._row(envelope.task_id)
            if existing is not None:
                if existing[0] == serialized:
                    return self.get(envelope.task_id)  # type: ignore[return-value]
                raise TaskConflictError("task_id already identifies another envelope")
            nonce = self.connection.execute(
                "SELECT task_id FROM endpoint_task_nonces WHERE nonce = ?", (envelope.nonce,),
            ).fetchone()
            if nonce is not None:
                raise TaskReplayError("task nonce has already been accepted")
            timestamp = now.isoformat()
            self.connection.execute(
                "INSERT INTO endpoint_task_nonces(nonce, task_id, accepted_at) VALUES (?, ?, ?)",
                (envelope.nonce, envelope.task_id, timestamp),
            )
            self.connection.execute(
                "INSERT INTO endpoint_tasks(task_id, envelope_json, state, state_version, revoked, updated_at) "
                "VALUES (?, ?, ?, 0, 0, ?)",
                (envelope.task_id, serialized, EndpointTaskState.QUEUED.value, timestamp),
            )
        return self.get(envelope.task_id)  # type: ignore[return-value]

    def compare_and_set(
        self,
        task_id: str,
        expected: EndpointTaskState,
        target: EndpointTaskState,
        *,
        now: datetime,
    ) -> bool:
        _utc(now, "now")
        if target not in _TRANSITIONS.get(expected, frozenset()):
            raise TaskProtocolError(f"invalid task transition: {expected.value} -> {target.value}")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE endpoint_tasks SET state = ?, state_version = state_version + 1, updated_at = ? "
                "WHERE task_id = ? AND state = ? AND revoked = 0",
                (target.value, now.isoformat(), task_id, expected.value),
            )
        return cursor.rowcount == 1

    def revoke(self, task_id: str, *, now: datetime) -> bool:
        _utc(now, "now")
        current = self.get(task_id)
        if current is None:
            return False
        if current.state is EndpointTaskState.REVOKED:
            return True
        if current.state not in _TRANSITIONS:
            return False
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE endpoint_tasks SET state = ?, state_version = state_version + 1, "
                "revoked = 1, updated_at = ? WHERE task_id = ? AND state = ? AND revoked = 0",
                (EndpointTaskState.REVOKED.value, now.isoformat(), task_id, current.state.value),
            )
        return cursor.rowcount == 1
