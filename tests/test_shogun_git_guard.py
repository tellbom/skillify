from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from skillify.agent.shogun.git_guard import write_git_guard


def _git(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False, env=env,
    )


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for args in (
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo), capture_output=True, text=True)
    r = subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True,
    )
    return r.stdout.strip()


def _run_wrapper(
    wrapper: Path, args: list[str], *, cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(wrapper), *args], cwd=str(cwd), capture_output=True, text=True, check=False,
    )


def test_wrapper_rejects_push_and_leaves_no_remote_effect(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    r = subprocess.run(
        ["git", "init", "--bare", str(origin)], capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr

    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["remote", "add", "origin", str(origin)], cwd=repo)

    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit" / "git-guard.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(wrapper, ["push", "origin", "HEAD:refs/heads/main"], cwd=repo)

    assert result.returncode != 0
    branches = subprocess.run(
        ["git", "branch", "-r"], cwd=str(origin), capture_output=True, text=True,
    ).stdout
    assert "main" not in branches

    lines = audit_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["rejected_subcommand"] == "push"
    assert "push" in record["argv"]


def test_wrapper_rejects_remote_add(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(wrapper, ["remote", "add", "origin", "https://example.invalid/x.git"], cwd=repo)

    assert result.returncode != 0
    remotes = _git(["remote"], cwd=repo).stdout
    assert "origin" not in remotes
    record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
    assert record["rejected_subcommand"] == "remote"


def test_wrapper_rejects_remote_set_url(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["remote", "add", "origin", "https://example.invalid/original.git"], cwd=repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(
        wrapper, ["remote", "set-url", "origin", "https://example.invalid/hijacked.git"], cwd=repo,
    )

    assert result.returncode != 0
    url = _git(["remote", "get-url", "origin"], cwd=repo).stdout.strip()
    assert url == "https://example.invalid/original.git"


def test_wrapper_rejects_config_credential_helper(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(wrapper, ["config", "credential.helper", "store"], cwd=repo)

    assert result.returncode != 0
    check = _git(["config", "--local", "--get", "credential.helper"], cwd=repo)
    assert check.stdout.strip() == ""
    record = json.loads(audit_log.read_text(encoding="utf-8").splitlines()[0])
    assert record["rejected_subcommand"] == "config"


def test_wrapper_passes_through_local_operations(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    status = _run_wrapper(wrapper, ["status", "--porcelain"], cwd=repo)
    assert status.returncode == 0
    assert status.stdout == ""

    (repo / "new.txt").write_text("content\n", encoding="utf-8")
    add = _run_wrapper(wrapper, ["add", "new.txt"], cwd=repo)
    assert add.returncode == 0

    commit = _run_wrapper(wrapper, ["commit", "-m", "add new file"], cwd=repo)
    assert commit.returncode == 0

    log = _run_wrapper(wrapper, ["log", "--oneline"], cwd=repo)
    assert log.returncode == 0
    assert "add new file" in log.stdout

    diff = _run_wrapper(wrapper, ["diff", "--name-status", f"{base_commit}..HEAD"], cwd=repo)
    assert diff.returncode == 0
    assert "new.txt" in diff.stdout

    assert not audit_log.exists() or audit_log.read_text(encoding="utf-8") == ""


def test_wrapper_allows_non_credential_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(wrapper, ["config", "user.name", "Someone Else"], cwd=repo)

    assert result.returncode == 0
    name = _git(["config", "--get", "user.name"], cwd=repo).stdout.strip()
    assert name == "Someone Else"


def test_wrapper_rejection_survives_missing_audit_log_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit-dir" / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    # Simulate the audit directory disappearing after generation (e.g. a
    # cleanup job ran) — the wrapper must still reject and exit non-zero
    # even though its own log write will now fail.
    audit_log.parent.rmdir()
    assert not audit_log.parent.exists()

    result = _run_wrapper(wrapper, ["push"], cwd=repo)

    assert result.returncode != 0
    assert not audit_log.parent.exists()


def test_wrapper_rejects_push_with_leading_c_global_option(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    r = subprocess.run(
        ["git", "init", "--bare", str(origin)], capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr

    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["remote", "add", "origin", str(origin)], cwd=repo)

    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(
        wrapper,
        ["-c", "protocol.version=2", "push", "origin", "HEAD:refs/heads/bypass-test"],
        cwd=repo,
    )

    assert result.returncode != 0
    branches = subprocess.run(
        ["git", "branch", "-r"], cwd=str(origin), capture_output=True, text=True,
    ).stdout
    assert "bypass-test" not in branches


def test_wrapper_rejects_remote_add_with_leading_capital_c_option(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(
        wrapper, ["-C", ".", "remote", "add", "evil", "http://evil.invalid"], cwd=repo,
    )

    assert result.returncode != 0
    remotes = _git(["remote"], cwd=repo).stdout
    assert "evil" not in remotes


def test_wrapper_rejects_combined_credential_and_push_bypass_attempt(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    r = subprocess.run(
        ["git", "init", "--bare", str(origin)], capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr

    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["remote", "add", "origin", str(origin)], cwd=repo)

    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(
        wrapper,
        [
            "-c", "credential.helper=!echo exfiltrated-token",
            "push", "origin", "HEAD:refs/heads/combined-attack",
        ],
        cwd=repo,
    )

    assert result.returncode != 0
    branches = subprocess.run(
        ["git", "branch", "-r"], cwd=str(origin), capture_output=True, text=True,
    ).stdout
    assert "combined-attack" not in branches
    check = _git(["config", "--local", "--get", "credential.helper"], cwd=repo)
    assert check.stdout.strip() == ""


def test_wrapper_rejects_remote_add_with_leading_v_option(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(
        wrapper, ["remote", "-v", "add", "evil", "http://evil.invalid"], cwd=repo,
    )

    assert result.returncode != 0
    remotes = _git(["remote"], cwd=repo).stdout
    assert "evil" not in remotes


def test_wrapper_rejects_remote_set_url_with_leading_verbose_option(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["remote", "add", "origin", "https://example.invalid/original.git"], cwd=repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(
        wrapper,
        ["remote", "--verbose", "set-url", "origin", "http://hijack.invalid"],
        cwd=repo,
    )

    assert result.returncode != 0
    url = _git(["remote", "get-url", "origin"], cwd=repo).stdout.strip()
    assert url == "https://example.invalid/original.git"


def test_wrapper_allows_remote_dash_v_listing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(["remote", "add", "origin", "https://example.invalid/original.git"], cwd=repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    result = _run_wrapper(wrapper, ["remote", "-v"], cwd=repo)

    assert result.returncode == 0
    assert "origin" in result.stdout
    assert not audit_log.exists() or audit_log.read_text(encoding="utf-8") == ""


def test_wrapper_allows_legitimate_global_option_on_safe_command(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    base_commit = _init_repo(repo)
    bin_dir = tmp_path / "bin"
    audit_log = tmp_path / "audit.jsonl"
    wrapper = write_git_guard(bin_dir, audit_log)

    status = _run_wrapper(wrapper, ["-c", "user.name=Someone Else", "status", "--porcelain"], cwd=repo)
    assert status.returncode == 0
    assert status.stdout == ""

    log = _run_wrapper(wrapper, ["-C", str(repo), "log", "--oneline"], cwd=tmp_path)
    assert log.returncode == 0
    assert base_commit[:7] in log.stdout or "initial" in log.stdout

    assert not audit_log.exists() or audit_log.read_text(encoding="utf-8") == ""
