"""Line-delimited control client for the local Node Agent Runtime Host."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any


class AgentHostError(RuntimeError):
    pass


class AgentHostClient:
    def __init__(self, entrypoint: Path, *, node: str = "node") -> None:
        if not entrypoint.is_absolute():
            raise ValueError("Agent Host entrypoint must be absolute")
        self.process = subprocess.Popen(
            [node, str(entrypoint)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._events: queue.Queue[dict[str, Any]] = queue.Queue()
        self._responses: dict[str, dict[str, Any]] = {}
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            command_id = event.get("commandId")
            if event.get("type") in {"command.completed", "command.failed"} and command_id:
                with self._condition:
                    self._responses[str(command_id)] = event
                    self._condition.notify_all()
            else:
                self._events.put(event)
        with self._condition:
            self._condition.notify_all()

    def command(self, kind: str, *, timeout: float = 30, **payload: Any) -> dict[str, Any]:
        command_id = uuid.uuid4().hex
        value = {"id": command_id, "type": kind, **payload}
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if self.process.poll() is not None:
            raise AgentHostError("Agent Host is not running")
        assert self.process.stdin is not None
        with self._write_lock:
            self.process.stdin.write(serialized + "\n")
            self.process.stdin.flush()
        with self._condition:
            ready = self._condition.wait_for(
                lambda: command_id in self._responses or self.process.poll() is not None,
                timeout=timeout,
            )
            if not ready:
                raise AgentHostError(f"Agent Host command timed out: {kind}")
            response = self._responses.pop(command_id, None)
        if response is None:
            error = ""
            if self.process.stderr is not None:
                error = self.process.stderr.read(2000)
            raise AgentHostError(f"Agent Host exited unexpectedly: {error}")
        if response["type"] == "command.failed":
            raise AgentHostError(str(response.get("payload", {}).get("error", "command failed")))
        return dict(response.get("payload") or {})

    def next_event(self, timeout: float = 0.5) -> dict[str, Any] | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
