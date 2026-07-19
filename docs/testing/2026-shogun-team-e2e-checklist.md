# Skillify Shogun Team Runtime · 测试环境验收清单

> 状态：待测试环境执行。开发环境只完成编译/静态装载校验，以下项目均未验证。
>
> 启用原则：全部 Go/No-Go 门禁通过前，`SKILLIFY_SHOGUN_TEAM_ENABLED` 与 `SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED` 必须保持关闭；`single/delegated` 不受影响。

## 环境与离线制品

- [ ] 上游许可为 MIT，批准版本、commit、制品哈希与 `infra/offline/shogun-manifest.json` 一致。
- [ ] 目标 Linux 发行版、CPU、glibc、tmux、flock、inotify-tools、Python、od 满足要求。
- [ ] 离线 bundle 包含预建 Python 环境、settings 模板和批准入口，不执行 `first_setup.sh`。
- [ ] 安装、启动、运行、停止和升级期间无公网下载、更新、通知或遥测。
- [ ] OpenCode、Claude Code 与内网模型端点版本已记录。

## 全 OpenCode formation

- [ ] 全 OpenCode formation 可启动 Coordinator、2～3 个 Worker 和独立 Reviewer。
- [ ] Team 能完成真实代码任务，工作包依赖、报告和独立审查由 Shogun 负责。
- [ ] OpenCode 声明式文件权限与互斥 allowed paths 生效，Worker 不互相覆盖文件。
- [ ] 每个 Worker 只加载其工作包声明的 MCP，网络访问为策略与 MCP allowlist 交集。
- [ ] 配置和运行参数不包含 dangerous 权限模式、明文凭据或公网通知配置。

## 全 Claude Code formation

- [ ] 全 Claude Code formation 可启动 Coordinator、2～3 个 Worker 和独立 Reviewer。
- [ ] Claude Code 使用单一共享内网模型端点完成真实代码任务。
- [ ] `--permission-mode` 使用受限模式，不使用 dangerous/bypass 权限模式。
- [ ] allowed paths、最小 MCP、无 push 凭据和默认拒绝网络边界生效。
- [ ] 配置、YAML、命令行、Agent 上下文和日志均不含明文凭据。

## 生命周期、并发与恢复

- [ ] 单 Endpoint 同时只运行一个 Team，额外 Team 排队或明确拒绝。
- [ ] 最大活动 Worker、最大并行模型调用、喂任务节奏和 Team 时长上限生效。
- [ ] 429/503 触发退避，空闲 Worker 不产生模型调用。
- [ ] 正常完成、取消、超时、Worker 卡死、CLI 崩溃和 Adapter 异常均得到明确最终状态。
- [ ] 停止或取消后 supervisor、watcher、tmux session、子进程、临时目录和临时凭据全部清理。
- [ ] Bridge 重启后能识别已有 Team，继续上报或安全终止，不重复执行任务。

## 控制面、事件与审计

- [ ] Web 仅在门禁开启后允许选择 Team，并可选择 preferred CLI、编辑和确认工作包。
- [ ] 工作包未确认前 Endpoint 不能领取 Team 任务。
- [ ] DM8 是服务端任务真相源；Shogun 运行目录不能直接覆盖服务端状态。
- [ ] Team/Worker/WorkPackage/Review 事件稳定映射、顺序合理且按 event ID 幂等。
- [ ] Web 只展示 Coordinator、Worker、Reviewer 等中立名称和真实时间线。
- [ ] 事件、Outbox、YAML、配置和日志不包含 Token、Key、Cookie、连接串、完整环境或原始对话。

## 已知阶段一边界

- [ ] 已确认 Worker 可执行 shell 是上游固有限制，测试范围限定为受信内网用户本机。
- [ ] 已确认阶段一没有 Worker worktree，依靠互斥 allowed paths，合并只由 Integration 角色执行。
- [ ] 已确认不支持同机多 Team、per-Claude 独立端点和混合 formation；这些不作为阶段一通过条件。
- [ ] 已确认失败时只禁用 Team，不恢复 Skillify 自研 Team 通讯或旧 Workflow Runtime。

## 最终结论

- [ ] 全 OpenCode formation 通过。
- [ ] 全 Claude Code formation 通过。
- [ ] License、Offline、Linux、Lifecycle、Security、Events、Workspace、Concurrency、Recovery 全部门禁通过。
- [ ] 集中系统级 hardening 已完成，发现、修复和复验记录已归档。
- [ ] Team Runtime 可由负责人批准启用。
