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
        "catalog": McpPackageConfig(
            "catalog", "skillctl", ("mcp", "serve", "catalog"),
            {"TARGET": "{runtime_target}"}, ("skills.search",), 1200,
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
    assert opencode.allowed_tools == ()
    assert set(claude.servers) == {"forgejo"}
    assert "codegraph" not in claude.servers
    assert claude.allowed_tools == ("mcp__forgejo__forgejo_get_issue",)


def test_runtime_target_is_projected_per_worker_provider(tmp_path) -> None:
    opencode = select_task_mcp(
        ("catalog",), catalog(), runtime="opencode", workspace=tmp_path,
    )
    claude = select_task_mcp(
        ("catalog",), catalog(), runtime="claude-code", workspace=tmp_path,
    )

    assert opencode.servers["catalog"]["environment"]["TARGET"] == "opencode"
    assert claude.servers["catalog"]["env"]["TARGET"] == "claude"


def test_unsupported_per_task_mode_records_permission_allowlist_downgrade(tmp_path) -> None:
    plan = select_task_mcp(
        ("codegraph",), catalog(), runtime="opencode", workspace=tmp_path,
        per_task_supported=False,
    )
    assert plan.downgraded is True
    assert "permission-allowlisted" in plan.log
