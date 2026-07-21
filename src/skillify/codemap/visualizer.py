"""Endpoint-local lifecycle wrapper for the pinned GitNexus visualizer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SUPPORTED_ENGINE = "gitnexus"
SUPPORTED_VERSION = "1.6.9"
SUPPORTED_COMMIT = "4227194ad7bdfbedc29a7fe20e09c6737ce0e744"
CODEMAP_WORKFLOWS = frozenset({
    "codemap.visualization.start",
    "codemap.visualization.stop",
    "codemap.visualization.open",
    "codemap.visualization.status",
})
_ALIAS = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SNAPSHOT_IGNORES = frozenset({
    ".git", ".gitnexus", ".venv", "node_modules", "__pycache__", ".pytest_cache",
})


class CodemapError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitNexusManifest:
    version: str
    commit_sha: str
    source_filename: str
    source_sha256: str
    source_url: str
    intranet_uri: str
    license_id: str
    license_sha256: str
    use_policy: str
    license_expires_at: str | None
    required_notice: str
    node_major: int
    entrypoint: str
    min_chrome_major: int | None
    bind_host: str


@dataclass(frozen=True)
class CodemapStatus:
    workspace_alias: str
    state: str
    engine_version: str = SUPPORTED_VERSION
    pid: int | None = None
    port: int | None = None
    detail: str = ""


def load_manifest(path: Path) -> GitNexusManifest:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        source = value["sourceArchive"]
        license_value = value["license"]
        runtime = value["runtime"]
        browser = value["browser"]
        isolation = value["isolation"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise CodemapError("GitNexus visualizer manifest is unavailable or invalid") from exc
    if (
        value.get("schemaVersion") != 1
        or value.get("engine") != SUPPORTED_ENGINE
        or value.get("version") != SUPPORTED_VERSION
        or value.get("commitSha") != SUPPORTED_COMMIT
        or license_value.get("id") != "PolyForm-Noncommercial-1.0.0"
        or license_value.get("usePolicy") != "personal-noncommercial-only"
        or license_value.get("expiresAt") is not None
        or runtime.get("nodeMajor") != 22
        or isolation.get("workspaceMode") != "snapshot"
        or isolation.get("bindHost") != "127.0.0.1"
    ):
        raise CodemapError("GitNexus visualizer approval metadata is invalid")
    digests = (source.get("sha256"), license_value.get("sha256"))
    if any(type(item) is not str or not re.fullmatch(r"[0-9a-f]{64}", item) for item in digests):
        raise CodemapError("GitNexus visualizer checksums are invalid")
    minimum = browser.get("minChromeMajor")
    if minimum is not None and (type(minimum) is not int or minimum < 1):
        raise CodemapError("GitNexus Chrome minimum is invalid")
    return GitNexusManifest(
        version=value["version"], commit_sha=value["commitSha"],
        source_filename=source["filename"], source_sha256=source["sha256"],
        source_url=source["sourceUrl"], intranet_uri=source["intranetUri"],
        license_id=license_value["id"], license_sha256=license_value["sha256"],
        use_policy=license_value["usePolicy"],
        license_expires_at=license_value["expiresAt"],
        required_notice=license_value["requiredNotice"], node_major=runtime["nodeMajor"],
        entrypoint=runtime["entrypoint"], min_chrome_major=minimum,
        bind_host=isolation["bindHost"],
    )


def verify_source_archive(path: Path, manifest: GitNexusManifest) -> None:
    try:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise CodemapError("GitNexus source archive is unavailable") from exc
    if digest != manifest.source_sha256:
        raise CodemapError("GitNexus source archive checksum mismatch")


def resolve_workspace_alias(alias: str, aliases: Mapping[str, str]) -> Path:
    if not _ALIAS.fullmatch(alias):
        raise CodemapError("workspace alias is invalid")
    raw = aliases.get(alias)
    if raw is None:
        raise CodemapError("workspace alias is not configured on this endpoint")
    try:
        return Path(raw).resolve(strict=True)
    except OSError as exc:
        raise CodemapError("workspace is unavailable") from exc


class GitNexusVisualizer:
    def __init__(
        self,
        *,
        manifest: GitNexusManifest,
        runtime_root: Path,
        state_root: Path,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        connect: Callable[[tuple[str, int], float], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        readiness_timeout: float = 30.0,
        readiness_interval: float = 0.2,
    ) -> None:
        self.manifest = manifest
        self.runtime_root = Path(runtime_root)
        self.state_root = Path(state_root)
        self._run = run
        self._popen = popen
        self._connect = connect or self._connect_tcp
        self._monotonic = monotonic
        self._sleep = sleep
        self.readiness_timeout = readiness_timeout
        self.readiness_interval = readiness_interval

    @staticmethod
    def _connect_tcp(address: tuple[str, int], timeout: float) -> Any:
        return socket.create_connection(address, timeout=timeout)

    def _port_ready(self, port: int) -> bool:
        try:
            connection = self._connect((self.manifest.bind_host, port), 0.5)
        except OSError:
            return False
        close = getattr(connection, "close", None)
        if close is not None:
            close()
        return True

    @staticmethod
    def _log_failure_detail(log_path: Path, fallback: str) -> str:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return fallback
        last_line = next((line.strip() for line in reversed(lines) if line.strip()), "")
        return f"{fallback}: {last_line[:300]}" if last_line else fallback

    @staticmethod
    def _process_exited(process: subprocess.Popen) -> bool:
        poll = getattr(process, "poll", None)
        return poll is not None and poll() is not None

    @staticmethod
    def _terminate_process(pid: int) -> None:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def _root(self, alias: str) -> Path:
        if not _ALIAS.fullmatch(alias):
            raise CodemapError("workspace alias is invalid")
        return self.state_root / alias

    def _state_path(self, alias: str) -> Path:
        return self._root(alias) / "runtime.json"

    def _command(self) -> list[str]:
        entrypoint = (self.runtime_root / self.manifest.entrypoint).resolve()
        if not entrypoint.is_file() or not entrypoint.is_relative_to(self.runtime_root.resolve()):
            raise CodemapError("approved GitNexus entrypoint is unavailable")
        node = shutil.which("node")
        if node is None:
            raise CodemapError("Node.js 22 is required for GitNexus")
        completed = self._run(
            [node, "--version"], capture_output=True, text=True, check=True, timeout=5,
        )
        match = re.match(r"v(\d+)\.", completed.stdout.strip())
        if match is None or int(match.group(1)) < self.manifest.node_major:
            raise CodemapError("Node.js 22 or newer is required for GitNexus")
        return [node, str(entrypoint)]

    def _environment(self, root: Path) -> dict[str, str]:
        home = root / "home"
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        allowed = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR") if key in os.environ}
        return {
            **allowed,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "GITNEXUS_SKIP_OPTIONAL_GRAMMARS": "1",
        }

    def prepare_snapshot(self, alias: str, workspace: Path) -> Path:
        root = self._root(alias)
        snapshot = root / "workspace"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copytree(
            Path(workspace).resolve(strict=True), snapshot,
            ignore=lambda _path, names: [name for name in names if name in _SNAPSHOT_IGNORES],
        )
        return snapshot

    def analyze(self, alias: str, workspace: Path) -> Path:
        root = self._root(alias)
        snapshot = self.prepare_snapshot(alias, workspace)
        command = self._command() + [
            "analyze", str(snapshot), "--skip-git", "--index-only", "--skip-skills",
            "--skip-agents-md", "--no-stats", "--name", f"skillify-{alias}",
        ]
        try:
            self._run(
                command, cwd=snapshot, env=self._environment(root), check=True,
                capture_output=True, text=True, timeout=900,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            stderr = getattr(exc, "stderr", None)
            last_line = ""
            if isinstance(stderr, str):
                lines = [line.strip() for line in stderr.splitlines() if line.strip()]
                last_line = next((
                    line
                    for marker in (
                        "cannot open shared object", "failed to load", "not found", "error:",
                    )
                    for line in lines if marker in line.casefold()
                ), lines[-1] if lines else "")
            detail = f": {last_line[:300]}" if last_line else ""
            raise CodemapError(f"GitNexus workspace scan failed{detail}") from exc
        if not (snapshot / ".gitnexus").is_dir():
            raise CodemapError("GitNexus did not create an index")
        return snapshot

    def start(self, alias: str, workspace: Path, *, port: int = 4747) -> CodemapStatus:
        current = self.status(alias)
        if current.state == "ready":
            return current
        if not 1024 <= port <= 65535:
            raise CodemapError("visualizer port must be between 1024 and 65535")
        root = self._root(alias)
        try:
            snapshot = self.analyze(alias, workspace)
        except CodemapError as exc:
            failed = CodemapStatus(alias, "failed", port=port, detail=str(exc))
            self._write_state(failed)
            return failed
        log_path = root / "gitnexus.log"
        log = log_path.open("ab")
        try:
            process = self._popen(
                self._command() + ["serve", "--host", self.manifest.bind_host, "--port", str(port)],
                cwd=snapshot, env=self._environment(root), stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        state = CodemapStatus(
            alias, "starting", pid=process.pid, port=port,
            detail="Waiting for GitNexus to bind its local port",
        )
        self._write_state(state)
        deadline = self._monotonic() + self.readiness_timeout
        while self._monotonic() < deadline:
            if self._process_exited(process):
                failed = CodemapStatus(
                    alias, "failed", port=port,
                    detail=self._log_failure_detail(
                        log_path, "GitNexus exited before binding its local port",
                    ),
                )
                self._write_state(failed)
                return failed
            if self._port_ready(port):
                ready = CodemapStatus(
                    alias, "ready", pid=process.pid, port=port, detail="GitNexus is ready",
                )
                self._write_state(ready)
                return ready
            self._sleep(self.readiness_interval)
        self._terminate_process(process.pid)
        failed = CodemapStatus(
            alias, "failed", port=port,
            detail=self._log_failure_detail(
                log_path, "GitNexus readiness timed out before binding its local port",
            ),
        )
        self._write_state(failed)
        return failed

    def status(self, alias: str) -> CodemapStatus:
        try:
            value = json.loads(self._state_path(alias).read_text(encoding="utf-8"))
            status = CodemapStatus(**value)
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            return CodemapStatus(alias, "stopped", detail="GitNexus is stopped")
        if status.state == "failed":
            return status
        if status.pid is None:
            return CodemapStatus(alias, "stopped", detail="GitNexus is stopped")
        try:
            os.kill(status.pid, 0)
        except OSError:
            self._state_path(alias).unlink(missing_ok=True)
            return CodemapStatus(alias, "stopped", detail="GitNexus process is not running")
        if status.port is None or not self._port_ready(status.port):
            starting = CodemapStatus(
                alias, "starting", pid=status.pid, port=status.port,
                detail="GitNexus process is running but its local port is not ready",
            )
            self._write_state(starting)
            return starting
        return status

    def stop(self, alias: str) -> CodemapStatus:
        current = self.status(alias)
        if current.pid is not None:
            self._terminate_process(current.pid)
        self._state_path(alias).unlink(missing_ok=True)
        return CodemapStatus(alias, "stopped", detail="GitNexus is stopped")

    def open(self, alias: str) -> CodemapStatus:
        current = self.status(alias)
        if current.state != "ready" or current.port is None:
            raise CodemapError("GitNexus must be started before opening it")
        chrome = self._chrome_command()
        self._popen(chrome + [f"http://127.0.0.1:{current.port}"], start_new_session=True)
        return current

    def doctor(self) -> dict[str, Any]:
        try:
            self._command()
            runtime = "ready"
        except CodemapError as exc:
            runtime = str(exc)
        try:
            chrome = self._chrome_command()[0]
        except CodemapError as exc:
            chrome = str(exc)
        return {
            "engine": SUPPORTED_ENGINE,
            "version": self.manifest.version,
            "licensePolicy": self.manifest.use_policy,
            "licenseExpiresAt": self.manifest.license_expires_at,
            "runtime": runtime,
            "chrome": chrome,
        }

    def _chrome_command(self) -> list[str]:
        candidates: Sequence[str] = (
            "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
        )
        for candidate in candidates:
            if path := shutil.which(candidate):
                return [path]
        mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if mac.is_file():
            return [str(mac)]
        raise CodemapError("approved Chrome is not installed")

    def _write_state(self, status: CodemapStatus) -> None:
        path = self._state_path(status.workspace_alias)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(status), sort_keys=True), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
