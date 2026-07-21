# 2026-07-21 当前工作区交付报告

## 交付范围

本次提交包含当前 Git 工作区的全部改动，主要包括：

- Shogun Team 真实任务终态闭环、凭据注入、队列契约、独立审查与清理增强。
- Codemap/GitNexus 服务端可视化方向的阶段性基础能力：源码快照、上传校验、隔离索引编排和任务清理。
- 对应测试、Dockerfile 调整与设计/实施文档。

## Shogun 验收结果

- 批准构件 SHA256：`add4076b3af18ce7c5c7a5c6e40211740ae0eab2ba54782ee05334e6b22921c8`。
- 最终真实任务：`cf2f5e4319c14db5ae6f68d8fc40cc21`，DM8 状态为 `succeeded`，版本为 15。
- 事件闭环覆盖团队准备、成员启动、工作包分配/完成、Gunshi 独立审查与 `team.completed`。
- 超时失败路径已验证为 `team.failed / skillify-timeout`。
- 任务结束后凭据文件、tmux 会话、运行目录、临时 worktree 和 Endpoint 待发送事件均已清理。
- 仅隔离 followup 配置启用 `installable=true` 与 `shogun_team_enabled=true`；仓库全局默认仍保持关闭。

## Codemap 当前状态

- 已实现可复现的 tracked-HEAD 源码快照及 SHA256 生成。
- 已实现带 Bearer Token、大小限制、校验和与路径穿越防护的临时上传入口。
- 已实现按任务隔离的 Docker 索引编排，以及幂等的源码/索引目录清理。
- 当前属于阶段性交付；真实目标虚拟机的 P1 环境门禁与后续 P2 尚未标记为 `env_verified`。

## 验证证据

- Codemap 聚焦测试：`35 passed`。
- Shogun Linux 聚焦回归：`149 passed, 2 skipped`。
- `git diff --check`：通过。
- Windows 全量 pytest 仍受既有 POSIX `fcntl` 导入限制；未将其误报为本轮通过。

本报告不记录测试环境密码、临时模型密钥或其他明文凭据。
