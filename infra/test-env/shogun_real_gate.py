"""Linux-only real-environment gate for the approved Shogun runtime.

The model credential is read once from stdin and is never written or printed.
This script intentionally exercises the lower-level lifecycle while the production
manifest remains non-installable.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from skillify.agent.shogun.config_gen import generate_config
from skillify.agent.shogun.credentials import PaneCredentialInjector
from skillify.agent.shogun.lifecycle import ProcessRuntime, ShogunLifecycle
from skillify.credentials.identities import AccessCredential


class _Profile:
    name = "shogun-real-model"
    credential_ref = "local://shogun-real-model"
    scopes = frozenset({"model.invoke"})


class _Broker:
    profiles = {_Profile.name: _Profile()}

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.calls = 0
        self.cleared = False

    def credential(self, profile, reference, scopes):
        assert profile == _Profile.name
        assert reference == _Profile.credential_ref
        assert scopes == _Profile.scopes
        self.calls += 1
        return AccessCredential(
            self.secret, "deepseek-model", scopes,
            datetime.now(timezone.utc) + timedelta(minutes=5),
        )

    def clear(self, reason):
        self.secret = ""
        self.cleared = reason == "team-stopped"


def _contains_secret(root: Path, secret: bytes) -> bool:
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    if secret in chunk:
                        return True
        except OSError:
            continue
    return False


def _cmdline_contains(secret: bytes) -> bool:
    for path in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if secret in path.read_bytes():
                return True
        except OSError:
            continue
    return False


def _panes() -> list[dict[str, str]]:
    result = subprocess.run(
        ["tmux", "list-panes", "-a", "-F", "#{session_name}\t#{pane_id}\t#{@agent_id}\t#{pane_current_command}"],
        check=True, capture_output=True, text=True,
    )
    panes = []
    for line in result.stdout.splitlines():
        session, pane, agent, command = (line.split("\t", 3) + ["", "", "", ""])[:4]
        panes.append({"session": session, "pane": pane, "agent": agent, "command": command})
    return panes


def _pane_diagnostics(secret: str) -> dict[str, list[str]]:
    diagnostics = {}
    for pane in _panes():
        if not pane["agent"]:
            continue
        captured = subprocess.run(
            ["tmux", "capture-pane", "-t", pane["pane"], "-p"],
            check=False, capture_output=True, text=True,
        ).stdout
        lines = [line.strip().replace(secret, "[redacted]") for line in captured.splitlines() if line.strip()]
        diagnostics[pane["agent"]] = lines[-8:]
    return diagnostics


def _task_evidence(root: Path, cli: str) -> dict[str, object]:
    evaluation = root / "evaluation" / f"{cli}-result.txt"
    task_files = list((root / "queue" / "tasks").glob("*.yaml"))
    report_files = list((root / "queue" / "reports").glob("*.yaml"))
    statuses = []
    for path in task_files:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(value, dict):
                task = value.get("task")
                status = task.get("status") if isinstance(task, dict) else value.get("status")
                if isinstance(status, str):
                    statuses.append(status)
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
    meaningful_reports = 0
    for path in report_files:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(value, dict):
                report = value.get("report")
                if (isinstance(report, dict) and report.get("task_id")) or value.get("task_id"):
                    meaningful_reports += 1
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
    return {
        "task_accepted": evaluation.is_file()
        and evaluation.read_text(encoding="utf-8").strip() == "ACCEPTED",
        "task_done_count": statuses.count("done"),
        "task_failed_count": statuses.count("failed"),
        "report_count": meaningful_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--guard", type=Path, required=True)
    parser.add_argument("--cli", choices=("opencode", "claude-code"), required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--credential-env", required=True)
    parser.add_argument("--settle-seconds", type=float, default=10)
    parser.add_argument("--task", action="store_true")
    parser.add_argument("--task-timeout", type=float, default=180)
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()

    secret = sys.stdin.read().strip()
    if not secret:
        raise SystemExit("model credential is required on stdin")
    if args.run_dir.exists() or args.guard.exists():
        raise SystemExit("real gate requires a fresh run directory and guard")

    broker = _Broker(secret)
    injector = PaneCredentialInjector(executables={args.cli: args.executable})
    channel = injector.prepare(
        {args.credential_env: _Profile.credential_ref}, broker=broker, run_dir=args.run_dir,
    )
    endpoint_name = "OPENCODE_BASE_URL" if args.cli == "opencode" else "ANTHROPIC_BASE_URL"
    generated = generate_config(
        install_root=args.install_root,
        run_dir=args.run_dir,
        preferred_cli=args.cli,
        worker_count=1,
        model=args.model,
        credential_refs={args.credential_env: _Profile.credential_ref},
        endpoint_environment={endpoint_name: args.endpoint},
    )
    generated.environment["PATH"] = os.pathsep.join((
        str(channel.launcher_dir), str(Path(args.executable).parent),
        str(Path.home() / ".local" / "bin"), "/usr/local/bin", "/usr/bin", "/bin",
    ))
    generated.environment["SKILLIFY_SHOGUN_CREDENTIAL_SOCKET"] = str(channel.socket_path)
    runtime = ProcessRuntime()
    lifecycle = ShogunLifecycle(runtime, args.guard)
    team = None
    secret_bytes = secret.encode()
    result: dict[str, object] = {"cli": args.cli}
    try:
        team = lifecycle.start(args.run_dir.name, generated, install_root=args.install_root)
        time.sleep(args.settle_seconds)
        if args.task:
            inbox = generated.queue_dir / "inbox" / "shogun.yaml"
            inbox.parent.mkdir(parents=True, exist_ok=True)
            inbox.write_text(yaml.safe_dump({"messages": [{
                "id": f"gate-{args.cli}", "from": "skillify",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "task_assigned",
                "content": (
                    "Run an acceptance task. Delegate one bounded implementation to ashigaru1, "
                    "request an independent Gunshi review, and record terminal queue status. "
                    f"Create evaluation/{args.cli}-result.txt containing ACCEPTED."
                ),
                "read": False,
            }]}), encoding="utf-8")
            inbox.chmod(0o600)
            deadline = time.monotonic() + args.task_timeout
            while time.monotonic() < deadline:
                evidence = _task_evidence(args.run_dir, args.cli)
                if (
                    evidence["task_accepted"]
                    and evidence["task_done_count"] >= 2
                    and evidence["task_failed_count"] == 0
                    and evidence["report_count"] >= 2
                ):
                    break
                time.sleep(2)
            result.update(_task_evidence(args.run_dir, args.cli))
        panes = _panes()
        result.update({
            "starter_exit": runtime.starters[0].poll(),
            "session_alive": runtime.is_alive(team.handle),
            "sessions": sorted({pane["session"] for pane in panes}),
            "pane_count": len(panes),
            "agent_commands": {
                pane["agent"]: pane["command"] for pane in panes if pane["agent"]
            },
            "broker_calls": broker.calls,
            "socket_mode": oct(channel.socket_path.stat().st_mode & 0o777),
            "secret_in_files": _contains_secret(args.run_dir, secret_bytes),
            "secret_in_cmdline": _cmdline_contains(secret_bytes),
        })
        if args.diagnostics:
            result["pane_diagnostics"] = _pane_diagnostics(secret)
    finally:
        secret = ""
        injector.destroy(channel)
        if team is not None:
            lifecycle.stop(team)
        result.update({
            "broker_cleared": broker.cleared,
            "run_removed": not args.run_dir.exists(),
            "guard_removed": not args.guard.exists(),
            "sessions_removed": not runtime.is_alive(team.handle) if team is not None else True,
        })
    print(json.dumps(result, sort_keys=True))
    expected_command = "opencode" if args.cli == "opencode" else "claude"
    expected_agents = {"shogun", "karo", "ashigaru1", "gunshi"}
    commands = result.get("agent_commands", {})
    return 0 if (
        result.get("starter_exit") == 0
        and result.get("session_alive") is True
        and result.get("sessions") == ["multiagent", "shogun"]
        and result.get("broker_calls", 0) >= 2
        and isinstance(commands, dict)
        and all(commands.get(agent) == expected_command for agent in expected_agents)
        and result.get("socket_mode") == "0o600"
        and result.get("secret_in_files") is False
        and result.get("secret_in_cmdline") is False
        and result.get("broker_cleared") is True
        and result.get("run_removed") is True
        and result.get("guard_removed") is True
        and result.get("sessions_removed") is True
        and (not args.task or (
            result.get("task_accepted") is True
            and result.get("task_done_count", 0) >= 2
            and result.get("task_failed_count") == 0
            and result.get("report_count", 0) >= 2
        ))
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
