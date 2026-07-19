# Skillify Agent 架构收敛 · 测试环境 E2E 清单

> 归并状态（2026-07-19）：本文验收项已完整归并至 `docs/testing/2026-07-17-post-ba3-test-environment-handoff.md`。本文冻结为历史来源，不在此勾选或销账；统一交付文档是唯一测试状态来源。
>
> 状态：待测试环境执行。本文只定义验收项，不代表已通过。
> 范围：真实 Linux、DM8、Keycloak/RBAC、OpenCode、Claude Code、CodeGraph、独立 devpi 与目标内网模型。

## 两执行器主链路

- [ ] OpenCode：Web 下发 → Bridge 拉取/确认 → Runner 执行 → 事件与构件回传 → Web 展示。
- [ ] Claude Code：Web 下发 → Bridge 拉取/确认 → Runner 执行 → 事件与构件回传 → Web 展示。
- [ ] 两条链路均覆盖正常完成、用户拒绝、等待计划审批、用户取消和执行器异常退出。

## 连接、租约与幂等

- [ ] 网络中断后 Outbox 补传，事件不丢失且不重复。
- [ ] 重复 pull 不重复执行同一任务。
- [ ] 重复 event 按 `event_id` 幂等处理。
- [ ] lease 续租、过期回收与重新领取符合状态机。
- [ ] OpenCode session 中断后按 session id 恢复且不重复执行。

## 权限与边界

- [ ] 未绑定 endpoint、越权 endpoint 与 workspace alias 越权均被拒绝。
- [ ] 服务端不主动连接端侧入站端口，Bridge 仅通过出站请求工作。
- [ ] 两执行器仅监听 `127.0.0.1`，停止任务后无残留进程。
- [ ] 执行器只访问授权 workspace 与 allowed paths。
- [ ] 凭据不写入持久文件、事件载荷或日志。

## CodeGraph 与 devpi

- [ ] CodeGraph 固定构件离线安装、哈希校验、建索引与增量更新通过。
- [ ] OpenCode 与 Claude Code 均可调用 `codegraph_explore`。
- [ ] CodeGraph 关闭遥测后无公网请求；不可用时执行器可继续使用原生检索。
- [ ] 独立 devpi 可通过 index URL 安装 Python 依赖。
- [ ] devpi 不可用时，主栈与非 Python Skill 安装不被阻断。

## Web 与审计证据

- [ ] Keycloak/RBAC 下仅授权用户可查看、下发、确认和取消任务。
- [ ] Web 时间线准确展示真实状态、测试汇总、Diff 统计、构件与失败原因。
- [ ] 导出两执行器全链路事件审计记录，并关联任务 ID、事件 ID 与构件 ID。
- [ ] 集中执行系统级 hardening，记录发现、修复与回归结果。

## 验收结论

- [ ] 所有阻断项销账，G-P7 通过。
- [ ] 未通过项已记录负责人、复现步骤和重新验收条件。
