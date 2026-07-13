# Skillify 完整后端 API 测试报告

- 测试时间：2026-07-13
- Git 基线：`7ec519ce39c0d3f0fb7680b92bd5002baf5ea1d5`
- 环境：CentOS 7 / Docker 23.0.6 / Compose 2.27.1 / DM8 V8 / Forgejo 10.0.3 / Keycloak 26.0 / devpi 6.13.0
- 凭据：全部通过临时环境变量或目标机 0600 文件提供，本报告已脱敏。

## 结论

部署完成，API 真实环境自动化 26/26 通过；三个创建/导入入口均完成 preview→确认→统一 publish；Forgejo 真实 Release 与 checksum、DM8 索引/任务、devpi 上传安装、重启恢复均通过。认证和临时对象跨用户隔离通过。

修复了 6 项会阻断真实部署/链路的代码或配置缺陷，详见 `known-issues.md`。失败发布和重复版本在 DM8 中留下预期的 failed job；社区表未污染。

尚未完整实测 TTL 等待 24 小时、真实超大 20/100MiB 边界包、外部网络浏览器入口、Forgejo webhook 的真实 tag push 投递，以及第二用户发布到已占 namespace 的最终 publish（跨用户 build/scan 隔离已测）。DM8 初始化脚本不幂等，PostgreSQL 16 在该旧内核不可用。这些风险使结论为：服务端核心链路具备进入人工评审条件，但应在评审确认已知风险后才进入客户端安装阶段。

**已暂停，等待人工评审。未执行目标主机 `skillctl install` 或 Agent 最终读取验证。**
