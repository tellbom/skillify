from __future__ import annotations

from skillify.tasks.mcp_injection import McpPackageConfig, select_task_mcp


def catalog():
    return {
        "codegraph": McpPackageConfig(
            "codegraph", "codegraph", ("serve", "--mcp"),
            {"CODEGRAPH_PROJECT_ROOT": "{workspace}"}, ("codegraph_explore",), 4000,
        ),
        "forgejo": McpPackageConfig(
            "forgejo", "skillctl", ("mcp", "serve", "forgejo"), {},
            ("forgejo.get_issue",), 1200,
        ),
    }


def test_only_declared_mcp_subset_is_rendered_per_runtime(tmp_path) -> None:
    opencode = select_task_mcp(
        ("codegraph",), catalog(), runtime="opencode", workspace=tmp_path,
    )
    claude = select_task_mcp(
        ("forgejo",), catalog(), runtime="claude-code", workspace=tmp_path,
    )

    assert set(opencode.servers) == {"codegraph"}
    assert opencode.servers["codegraph"]["environment"]["CODEGRAPH_PROJECT_ROOT"] == str(tmp_path)
    assert set(claude.servers) == {"forgejo"}
    assert "codegraph" not in claude.servers


def test_unsupported_per_task_mode_records_permission_allowlist_downgrade(tmp_path) -> None:
    plan = select_task_mcp(
        ("codegraph",), catalog(), runtime="opencode", workspace=tmp_path,
        per_task_supported=False,
    )
    assert plan.downgraded is True
    assert "permission-allowlisted" in plan.log
