# Claude Code Team 人工放行

Claude Code Team 在 Skillify 中采用半自动运行：Skillify 负责创建隔离配置、按 worker
分配独立 git worktree、启动 formation 和回收进程；Claude Code 请求工具权限时，由在场
用户在端侧终端逐次确认。系统不会自动代替用户批准。

## 操作步骤

1. 在端侧运行 `skillctl bridge start`，并保持 formation 所在的 tmux 终端可见。
2. Web 下发 Team 任务后，核对固定表单、工作包、允许路径和验收命令，再确认任务。
3. Claude Code 终端出现工具权限请求时，核对 worker、工作包和命令后手工允许或拒绝。
4. 等待 worker 完成、独立审查完成和 Skillify 派生的最终终态；任务取消或失败后检查
   formation 已退出且 worktree 已清理。

## 权限表达限制

上游 `ashigaru` 的公开配置只支持角色级 `read_allow/read_deny/edit_allow/edit_deny`，
不能完整表达每个 WorkPackage 的所有权限字段。因此 Skillify 不声称 Claude 原生配置已
实现逐工作包权限隔离。当前互斥边界是每个 worker 使用独立 git worktree，配置生成仍按
worker 的 `allowedPaths` 收敛读写范围，最终集成由独立 integration worktree 完成。

代码固定使用 `--permission-mode default`。仓库不得加入
`--dangerously-skip-permissions` 或其他自动批准路径；日志、YAML 和命令行也不得写入
模型或 Forgejo 凭据。
