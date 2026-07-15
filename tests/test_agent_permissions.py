from __future__ import annotations

import json
import multiprocessing
import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

import pytest

from skillify.agent.permissions import (
    OperationKind,
    OperationRequest,
    PermissionAction,
    PermissionDecision,
    PermissionManifest,
    PermissionValidationError,
    merge_permissions,
    summarize_permissions,
    write_authorization_audit,
)


def policy(
    policy_id: str = "skill:demo",
    *,
    read: tuple[str, ...] = ("*",),
    write: tuple[str, ...] = ("*",),
    command: dict[str, str] | None = None,
    network: tuple[str, ...] = ("*",),
    mcp: tuple[str, ...] = ("*",),
    database: tuple[str, ...] = ("*",),
    unattended: bool = True,
    confirm: tuple[str, ...] = (),
) -> PermissionManifest:
    return PermissionManifest(
        policy_id=policy_id,
        read_paths=read,
        write_paths=write,
        commands=command or {"*": "allow"},
        network_domains=network,
        mcp_servers=mcp,
        database_resources=database,
        unattended=unattended,
        confirm=confirm,
    )


def request(kind: OperationKind, workspace: Path, **kwargs: object) -> OperationRequest:
    return OperationRequest(kind=kind, workspace=workspace, **kwargs)


def _append_audit_process(audit_path: str, workspace: str, start: int, count: int) -> None:
    operation = OperationRequest(
        kind=OperationKind.MCP,
        workspace=Path(workspace),
        mcp_server="filesystem",
    )
    decision = merge_permissions((policy(),)).decide(operation)
    for index in range(start, start + count):
        write_authorization_audit(
            Path(audit_path), task_id=f"process-{index}", request=operation, decision=decision
        )


def test_later_allow_cannot_override_earlier_deny(tmp_path: Path) -> None:
    merged = merge_permissions(
        (
            policy("task", command={"rm *": "deny"}),
            policy("skill", command={"rm *": "allow"}),
        )
    )
    operation = request(OperationKind.COMMAND, tmp_path, command=("rm", "-rf", "build"))
    decision = merged.decide(operation)
    assert decision.action is PermissionAction.DENY
    assert decision.matched_policy_ids == ("task", "skill")


def test_allowlists_require_every_policy_to_allow(tmp_path: Path) -> None:
    merged = merge_permissions(
        (policy("skill", network=("git.internal",)), policy("task", network=("docs.internal",)))
    )
    decision = merged.decide(request(OperationKind.NETWORK, tmp_path, domain="git.internal"))
    assert decision.action is PermissionAction.DENY
    assert "allowlist-miss" in decision.reason_codes


def test_empty_policy_set_and_empty_allowlist_fail_closed(tmp_path: Path) -> None:
    operation = request(OperationKind.NETWORK, tmp_path, domain="docs.internal")
    assert merge_permissions(()).decide(operation).action is PermissionAction.DENY
    assert policy(network=()).decide(operation).action is PermissionAction.DENY


def test_path_allowlist_uses_segment_globs_and_resolved_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = policy(read=("docs/*.md",), write=("output/**",))
    assert manifest.decide(request(OperationKind.READ_PATH, workspace, path="docs/guide.md")).action is PermissionAction.ALLOW
    assert manifest.decide(request(OperationKind.READ_PATH, workspace, path="docs/nested/guide.md")).action is PermissionAction.DENY
    assert manifest.decide(request(OperationKind.WRITE_PATH, workspace, path="output/a/b.txt")).action is PermissionAction.ALLOW
    assert manifest.decide(request(OperationKind.WRITE_PATH, workspace, path="../escape.txt")).action is PermissionAction.DENY


def test_repeated_globstars_do_not_trigger_exponential_backtracking(tmp_path: Path) -> None:
    pattern = "/".join(["**"] * 16 + ["never"])
    candidate = "/".join(["segment"] * 16)
    manifest = policy(read=(pattern,))
    started = time.monotonic()
    assert manifest.decide(request(OperationKind.READ_PATH, tmp_path, path=candidate)).action is PermissionAction.DENY
    assert time.monotonic() - started < 1.0


def test_existing_symlink_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    operation = request(OperationKind.WRITE_PATH, workspace, path="linked/secret.txt")
    assert policy().decide(operation).action is PermissionAction.DENY


def test_command_patterns_match_argv_without_shell_reconstruction(tmp_path: Path) -> None:
    manifest = policy(command={"echo safe": "allow", "python -m pytest": "allow"})
    safe = request(OperationKind.COMMAND, tmp_path, command=("echo", "safe"))
    injected = request(OperationKind.COMMAND, tmp_path, command=("echo", "safe; rm -rf /"))
    extra = request(OperationKind.COMMAND, tmp_path, command=("python", "-m", "pytest", "--pdb"))
    assert manifest.decide(safe).action is PermissionAction.ALLOW
    assert manifest.decide(injected).action is PermissionAction.DENY
    assert manifest.decide(extra).action is PermissionAction.DENY


def test_command_final_star_matches_argv_tail_but_not_other_executable(tmp_path: Path) -> None:
    manifest = policy(command={"git status *": "allow"})
    allowed = request(OperationKind.COMMAND, tmp_path, command=("git", "status", "--short", "--branch"))
    wrong = request(OperationKind.COMMAND, tmp_path, command=("git-status", "--short", "--branch"))
    assert manifest.decide(allowed).action is PermissionAction.ALLOW
    assert manifest.decide(wrong).action is PermissionAction.DENY


def test_executable_basename_cannot_bypass_explicit_deny(tmp_path: Path) -> None:
    manifest = policy(command={"rm *": "deny", "*": "allow"})
    operation = request(OperationKind.COMMAND, tmp_path, command=("/bin/rm", "-rf", "build"))
    assert manifest.decide(operation).action is PermissionAction.DENY


def test_allow_executable_name_does_not_authorize_attacker_controlled_path(tmp_path: Path) -> None:
    manifest = policy(command={"git *": "allow"})
    operation = request(OperationKind.COMMAND, tmp_path, command=("/tmp/evil/git", "status"))
    assert manifest.decide(operation).action is PermissionAction.DENY


@pytest.mark.parametrize(
    ("allowed", "rejected"),
    [
        ("api.example.com", "api.example.com.evil"),
        ("BÜCHER.example", "bücher.example.evil"),
        ("127.0.0.1", "127.0.0.10"),
    ],
)
def test_domain_matching_is_normalized_and_not_suffix_based(
    tmp_path: Path, allowed: str, rejected: str
) -> None:
    manifest = policy(network=(allowed,))
    assert manifest.decide(request(OperationKind.NETWORK, tmp_path, domain=allowed.lower() + ".")).action is PermissionAction.ALLOW
    assert manifest.decide(request(OperationKind.NETWORK, tmp_path, domain=rejected)).action is PermissionAction.DENY


def test_domain_wildcard_matches_subdomains_but_not_apex_or_suffix_trick(tmp_path: Path) -> None:
    manifest = policy(network=("*.example.com",))
    assert manifest.decide(request(OperationKind.NETWORK, tmp_path, domain="a.b.example.com")).action is PermissionAction.ALLOW
    assert manifest.decide(request(OperationKind.NETWORK, tmp_path, domain="example.com")).action is PermissionAction.DENY
    assert manifest.decide(request(OperationKind.NETWORK, tmp_path, domain="example.com.evil")).action is PermissionAction.DENY


@pytest.mark.parametrize(
    "numeric_host",
    ["0177.0.0.1", "2130706433", "127.1", "0x7f.0.0.1", "0x7f.1"],
)
def test_ambiguous_numeric_hosts_are_rejected(numeric_host: str) -> None:
    with pytest.raises(ValueError, match="invalid domain"):
        policy(network=(numeric_host,))


@pytest.mark.parametrize(
    "unicode_numeric_host",
    ["２１３０７０６４３３", "０１７７.０.０.１", "１２７.１", "0x７f.1"],
)
def test_post_idna_numeric_hosts_are_rejected(unicode_numeric_host: str) -> None:
    with pytest.raises(PermissionValidationError, match="invalid domain"):
        policy(network=(unicode_numeric_host,))


@pytest.mark.parametrize("shell", ["sh", "bash", "zsh", "powershell"])
def test_shell_entrypoints_are_always_confirmation_bound(tmp_path: Path, shell: str) -> None:
    operation = request(OperationKind.COMMAND, tmp_path, command=(shell, "-c", "rm -rf /"))
    assert policy().decide(operation).action is PermissionAction.ASK


@pytest.mark.parametrize(
    "argv",
    [
        ("busybox", "rm", "-rf", "build"),
        ("/bin/toybox", "rm", "-rf", "build"),
        ("busybox", "--help", "su"),
        ("/usr/bin/toybox", "-x", "sh", "-c", "id"),
    ],
)
def test_multicall_dangerous_applets_require_confirmation(
    tmp_path: Path, argv: tuple[str, ...]
) -> None:
    operation = request(OperationKind.COMMAND, tmp_path, command=argv)
    assert policy().decide(operation).action is PermissionAction.ASK


@pytest.mark.parametrize(
    "operation",
    [
        lambda root: request(OperationKind.COMMAND, root, command=("rm", "-rf", "build")),
        lambda root: request(OperationKind.COMMAND, root, command=("sudo", "make", "install")),
        lambda root: request(OperationKind.COMMAND, root, command=("sudoedit", "/etc/hosts")),
        lambda root: request(OperationKind.COMMAND, root, command=("env", "sudo", "make", "install")),
        lambda root: request(OperationKind.CREDENTIAL, root, credential_name="MODEL_TOKEN"),
        lambda root: request(OperationKind.DATABASE, root, database_resource="orders", database_write=True),
        lambda root: request(OperationKind.WRITE_PATH, root, path="../outside.txt"),
    ],
)
def test_dangerous_actions_never_run_unattended(tmp_path: Path, operation: object) -> None:
    decision = merge_permissions((policy(),)).decide(operation(tmp_path))  # type: ignore[operator]
    assert decision.action in {PermissionAction.ASK, PermissionAction.DENY}


def test_web_code_write_requires_endpoint_confirmation(tmp_path: Path) -> None:
    operation = request(
        OperationKind.WRITE_PATH,
        tmp_path,
        path="src/app.py",
        origin="web",
        unattended=True,
    )
    decision = merge_permissions((policy(),)).decide(operation)
    assert decision.action is PermissionAction.ASK
    assert "web-write-confirmation" in decision.reason_codes


def test_web_origin_cannot_use_unattended_write_for_extensionless_code(tmp_path: Path) -> None:
    operation = request(
        OperationKind.WRITE_PATH,
        tmp_path,
        path="Makefile",
        origin=" WEB ",
        unattended=True,
    )
    assert merge_permissions((policy(),)).decide(operation).action is PermissionAction.ASK


@pytest.mark.parametrize("origin", ["", "browser", "remote", "ｗｅｂ"])
def test_unknown_or_confusable_operation_origins_fail_closed(
    tmp_path: Path, origin: str
) -> None:
    with pytest.raises(PermissionValidationError, match="origin"):
        request(
            OperationKind.WRITE_PATH,
            tmp_path,
            path="src/app.py",
            origin=origin,
            unattended=True,
        )


def test_unattended_and_explicit_confirmation_form_restrictive_lattice(tmp_path: Path) -> None:
    operation = request(OperationKind.NETWORK, tmp_path, domain="docs.internal", unattended=True)
    merged = merge_permissions(
        (
            policy("skill", network=("docs.internal",), unattended=True),
            policy("task", network=("docs.internal",), unattended=False),
            policy("workflow", network=("docs.internal",), confirm=("network",)),
        )
    )
    decision = merged.decide(operation)
    assert decision.action is PermissionAction.ASK
    assert set(decision.matched_policy_ids) == {"skill", "task", "workflow"}


def test_legacy_permission_tags_normalize_to_restrictive_named_policy(tmp_path: Path) -> None:
    manifest = PermissionManifest.from_value("skill:legacy", ["network", "deny:command"])
    network = manifest.decide(request(OperationKind.NETWORK, tmp_path, domain="docs.internal"))
    command = manifest.decide(request(OperationKind.COMMAND, tmp_path, command=("echo", "ok")))
    assert network.action is PermissionAction.ASK
    assert command.action is PermissionAction.DENY
    assert manifest.legacy_tags == ("network", "deny:command")


@pytest.mark.parametrize(
    "value",
    [
        {"readPaths": "*"},
        {"mcpServers": "filesystem"},
        {"unattended": 1},
        {"commands": []},
        {"confirm": "command"},
        {1: [], "unknown": []},
    ],
)
def test_direct_structured_policy_parser_rejects_schema_type_confusion(value: object) -> None:
    with pytest.raises(ValueError):
        PermissionManifest.from_value("task:bad", value)


def test_declared_mapping_and_sequence_inputs_are_snapshotted(tmp_path: Path) -> None:
    command_source = {"echo *": "allow"}
    environment_source = {"SAFE_NAME": "sensitive-value"}
    manifest = PermissionManifest(
        policy_id="task:snapshot",
        commands=MappingProxyType(command_source),
    )
    operation = OperationRequest(
        kind=OperationKind.COMMAND,
        workspace=tmp_path,
        command=("echo", "ok"),
        environment=MappingProxyType(environment_source),
    )
    command_source["echo *"] = "deny"
    environment_source["SAFE_NAME"] = "changed"
    assert manifest.decide(operation).action is PermissionAction.ALLOW
    assert operation.environment["SAFE_NAME"] == "sensitive-value"
    assert PermissionManifest.from_value("task:tuple", {"readPaths": ("docs/**",)})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "command"},
        {"unattended": "TOP_SECRET"},
        {"database_write": 1},
        {"command": ["echo", "ok"]},
        {"domain": 123},
        {"origin": b"web"},
        {"environment": [("TOKEN", "secret")]},
    ],
)
def test_operation_request_rejects_forged_runtime_types(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    values: dict[str, object] = {"kind": OperationKind.NETWORK, "workspace": tmp_path}
    values.update(kwargs)
    with pytest.raises(PermissionValidationError):
        OperationRequest(**values)  # type: ignore[arg-type]


def test_permission_decision_requires_exact_enum_bool_and_tuple_types() -> None:
    with pytest.raises(PermissionValidationError):
        PermissionDecision("allow", ("task",), ())  # type: ignore[arg-type]
    with pytest.raises(PermissionValidationError):
        PermissionDecision(PermissionAction.ALLOW, ["task"], ())  # type: ignore[arg-type]


def test_runtime_policy_and_request_resource_limits_fail_stably(tmp_path: Path) -> None:
    with pytest.raises(PermissionValidationError, match="entries"):
        policy(read=tuple(f"docs/{index}" for index in range(257)))
    with pytest.raises(PermissionValidationError, match="glob segments"):
        policy(read=("/".join(["**"] * 129),))
    with pytest.raises(PermissionValidationError, match="pattern length"):
        policy(command={"x" * 513: "allow"})
    with pytest.raises(PermissionValidationError, match="arguments"):
        request(OperationKind.COMMAND, tmp_path, command=tuple("x" for _ in range(257)))
    with pytest.raises(PermissionValidationError, match="argument length"):
        request(OperationKind.COMMAND, tmp_path, command=("x" * 4097,))
    with pytest.raises(PermissionValidationError, match="path length"):
        request(OperationKind.WRITE_PATH, tmp_path, path="x" * 4097)
    with pytest.raises(PermissionValidationError, match="policies"):
        merge_permissions(tuple(policy(f"task:{index}") for index in range(65)))


def test_policy_decision_revalidates_forged_oversized_request(tmp_path: Path) -> None:
    operation = request(OperationKind.WRITE_PATH, tmp_path, path="output.txt")
    object.__setattr__(operation, "path", "x" * 4097)
    with pytest.raises(PermissionValidationError, match="path length"):
        policy().decide(operation)


def test_summary_has_no_absolute_workspace_or_raw_command_arguments(tmp_path: Path) -> None:
    manifest = policy(
        write=("src/**",),
        command={"python -m secret.module *": "ask"},
        network=("docs.internal",),
        mcp=("filesystem",),
        database=("analytics",),
        confirm=("database",),
    )
    summary = summarize_permissions(merge_permissions((manifest,)), tmp_path)
    encoded = json.dumps(summary, sort_keys=True)
    assert str(tmp_path) not in encoded
    assert "secret.module" not in encoded
    assert summary["policies"][0]["commandExecutables"] == ["python"]
    assert summary["policies"][0]["writePaths"] == ["src/**"]


def test_audit_is_jsonl_redacted_and_mode_0600(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audit_path = tmp_path / "audit" / "authorization.jsonl"
    operation = request(
        OperationKind.COMMAND,
        workspace,
        command=("curl", "--header", "Authorization: Bearer top-secret", "https://example.invalid"),
        prompt="password=top-secret",
        environment={"MODEL_TOKEN": "top-secret"},
    )
    decision = merge_permissions((policy(command={"curl *": "ask"}),)).decide(operation)
    write_authorization_audit(audit_path, task_id="task-123", request=operation, decision=decision)
    raw = audit_path.read_text(encoding="utf-8")
    record = json.loads(raw)
    assert record["operation"] == "command"
    assert record["resource"] == {"executable": "curl"}
    assert "top-secret" not in raw
    assert "MODEL_TOKEN" not in raw
    assert "Authorization" not in raw
    assert stat.S_IMODE(audit_path.stat().st_mode) == 0o600


def test_audit_redacts_external_path_and_credential_name(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    audit_path = tmp_path / "authorization.jsonl"
    outside = tmp_path / "private" / "customer.txt"
    path_operation = request(OperationKind.WRITE_PATH, workspace, path=outside)
    credential_operation = request(OperationKind.CREDENTIAL, workspace, credential_name="CUSTOMER_PASSWORD")
    for operation in (path_operation, credential_operation):
        decision = merge_permissions((policy(),)).decide(operation)
        write_authorization_audit(audit_path, task_id="task-123", request=operation, decision=decision)
    raw = audit_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw.splitlines()]
    assert records[0]["resource"]["path"].startswith("<external:")
    assert str(outside) not in raw
    assert "CUSTOMER_PASSWORD" not in raw
    assert records[1]["resource"] == {"credential": "<redacted>"}


def test_audit_appends_complete_records_under_concurrency(tmp_path: Path) -> None:
    audit_path = tmp_path / "authorization.jsonl"
    operation = request(OperationKind.MCP, tmp_path, mcp_server="filesystem")
    decision = merge_permissions((policy(),)).decide(operation)

    def append(index: int) -> None:
        write_authorization_audit(
            audit_path,
            task_id=f"task-{index}",
            request=operation,
            decision=decision,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(32)))
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 32
    assert {record["taskId"] for record in records} == {f"task-{i}" for i in range(32)}


def test_audit_rejects_preexisting_hardlink(tmp_path: Path) -> None:
    target = tmp_path / "valuable.txt"
    target.write_text("keep", encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    audit_path.hardlink_to(target)
    operation = request(OperationKind.MCP, tmp_path, mcp_server="filesystem")
    decision = merge_permissions((policy(),)).decide(operation)
    with pytest.raises(OSError, match="regular single-link"):
        write_authorization_audit(
            audit_path, task_id="task-123", request=operation, decision=decision
        )
    assert target.read_text(encoding="utf-8") == "keep"


def test_audit_rejects_symlinked_parent_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(outside, target_is_directory=True)
    operation = request(OperationKind.MCP, tmp_path, mcp_server="filesystem")
    decision = merge_permissions((policy(),)).decide(operation)
    with pytest.raises(OSError):
        write_authorization_audit(
            linked_parent / "audit.jsonl",
            task_id="task-123",
            request=operation,
            decision=decision,
        )
    assert not (outside / "audit.jsonl").exists()


def test_audit_rejects_leaf_symlink_without_mutating_target(tmp_path: Path) -> None:
    target = tmp_path / "valuable.txt"
    target.write_text("keep", encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    audit_path.symlink_to(target)
    operation = request(OperationKind.MCP, tmp_path, mcp_server="filesystem")
    decision = merge_permissions((policy(),)).decide(operation)
    with pytest.raises(OSError):
        write_authorization_audit(
            audit_path, task_id="task-123", request=operation, decision=decision
        )
    assert target.read_text(encoding="utf-8") == "keep"


def test_audit_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.fifo"
    os.mkfifo(audit_path, 0o600)
    operation = request(OperationKind.MCP, tmp_path, mcp_server="filesystem")
    decision = merge_permissions((policy(),)).decide(operation)
    started = time.monotonic()
    with pytest.raises(OSError):
        write_authorization_audit(
            audit_path, task_id="task-123", request=operation, decision=decision
        )
    assert time.monotonic() - started < 1.0


def test_audit_appends_complete_records_across_processes(tmp_path: Path) -> None:
    audit_path = tmp_path / "authorization.jsonl"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_append_audit_process,
            args=(str(audit_path), str(tmp_path), worker * 12, 12),
        )
        for worker in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 48
    assert {record["taskId"] for record in records} == {
        f"process-{index}" for index in range(48)
    }


def test_audit_boundary_revalidates_forged_objects_before_file_mutation(tmp_path: Path) -> None:
    audit_path = tmp_path / "authorization.jsonl"
    audit_path.write_text("keep\n", encoding="utf-8")
    forged_request = object.__new__(OperationRequest)
    object.__setattr__(forged_request, "kind", type("ForgedKind", (), {"value": "TOP_SECRET"})())
    object.__setattr__(forged_request, "unattended", "TOP_SECRET")
    forged_decision = object.__new__(PermissionDecision)
    object.__setattr__(
        forged_decision, "action", type("ForgedAction", (), {"value": "TOP_SECRET"})()
    )
    object.__setattr__(forged_decision, "matched_policy_ids", ("task",))
    object.__setattr__(forged_decision, "reason_codes", ())
    with pytest.raises(PermissionValidationError):
        write_authorization_audit(
            audit_path,
            task_id="task-123",
            request=forged_request,
            decision=forged_decision,
        )
    assert audit_path.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize("task_id", ["", "contains space", "../escape", "x" * 129])
def test_audit_rejects_unbounded_or_unsafe_task_ids(tmp_path: Path, task_id: str) -> None:
    operation = request(OperationKind.MCP, tmp_path, mcp_server="filesystem")
    decision = merge_permissions((policy(),)).decide(operation)
    with pytest.raises(ValueError, match="task_id"):
        write_authorization_audit(
            tmp_path / "audit.jsonl", task_id=task_id, request=operation, decision=decision
        )
