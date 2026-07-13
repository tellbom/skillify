# 完整后端 API 测试计划

在目标服务器内执行 `scripts/api-smoke/full_backend_api.py`，通过环境变量提供 URL、用户和密码。覆盖：健康检查；正确/缺失/错误 JWT；引导式 partial/PATCH/files/revision/confirm/publish；标准 zip preview/publish/重复版本；外部单/多候选、跨用户隔离、重复选择、补字段、publish；搜索可见；Forgejo Release/资产/checksum；DM8 终态；devpi 上传安装；全栈重启恢复。

安全异常另由仓库测试覆盖路径穿越、符号链接、解压大小、文件数、非法 frontmatter/candidate ID；真实环境 smoke 覆盖路径穿越和无 `SKILL.md`。客户端最终安装明确不在本阶段执行。

