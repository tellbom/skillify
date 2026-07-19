# Skillify 端侧 MCP 与 Agent 委派 · 测试环境 E2E 清单

> 归并状态（2026-07-19）：本文验收项已完整归并至 `docs/testing/2026-07-17-post-ba3-test-environment-handoff.md`。本文冻结为历史来源，不在此勾选或销账；统一交付文档是唯一测试状态来源。
>
> 状态：待测试环境执行。勾选项必须附任务 ID、事件审计和脱敏日志证据。

## 官方 SDK 与 Adapter

- [ ] 从内网 devpi 安装锁定的 `mcp==1.28.1`，构件哈希与 manifest 一致。
- [ ] `skillctl mcp serve db-readonly` 连接真实 DM8 只读账号并验证方言、行数、超时和脱敏。
- [ ] `skillctl mcp serve forgejo` 使用最小 scope 读取 Issue/CI；写工具逐项授权。
- [ ] `skillctl mcp serve documents` 只检索允许的文档集合。
- [ ] REST Adapter 只访问 manifest 与本地策略共同允许的内网 host/port/protocol。
- [ ] Adapter 取消、超时、403、网络不通和进程崩溃均产生明确事件。

## 凭据与四类身份

- [ ] Web 用户 Token 只能创建、审批和查看任务，不能作为 Endpoint 机器身份。
- [ ] Bridge 使用真实 device token 或 mTLS 拉取、心跳和上报。
- [ ] 用户委托身份完成 PKCE/Device/Token Exchange，Token audience/scope 与目标服务一致。
- [ ] 服务账号通过 Client Credentials 获取目标专用最小权限 Token。
- [ ] Token 过期后 Broker 刷新；取消、退出和超时后清理临时凭据。
- [ ] Agent、MCP、Bridge、业务 API、配置和事件日志均不含 Token、Secret、Cookie 或连接串。

## 工作包与双执行器

- [ ] Web suggested 模式产生工作包，用户编辑 allowed paths、权限和并行标志后确认。
- [ ] OpenCode 原生主 Agent 根据确认工作包管理子 Agent。
- [ ] Claude Code 原生主 Agent 根据确认工作包管理子 Agent。
- [ ] 控制面完成任务不依赖执行器未承诺的子会话内部事件。
- [ ] OpenCode 任务只加载工作包声明的最小 MCP 集合。
- [ ] Claude Code `--mcp-config` 只加载工作包声明的最小 MCP 集合。
- [ ] 不支持 per-task MCP 时记录降级，并由全局安装 + 任务权限 allowlist 拒绝未声明工具。

## 终验

- [ ] OpenCode 完成一次 Web→Bridge→工作包确认→MCP→事件回传全链路。
- [ ] Claude Code 完成一次 Web→Bridge→工作包确认→MCP→事件回传全链路。
- [ ] 全程无公网下载、更新或遥测。
- [ ] 所有失败路径留存可检索事件和审计证据。
- [ ] G-E 通过；未完成项均记录负责人、复现步骤和复验条件。
