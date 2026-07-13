# 目标客户机 Skill 安装验证

- 时间：2026-07-13（Asia/Shanghai）
- 客户机：银河麒麟桌面操作系统 V10 SP1，用户 `fzq`
- Skillify 服务：目标测试服务器桥接入口
- 凭据：均存放于客户机权限 0600 的配置文件，本文不记录明文

## 工具与模型

- 用户级 Node.js 24.18.0、uv 0.11.28。
- Claude Code 2.1.179；使用 DeepSeek Anthropic 兼容端点和 `deepseek-v4-flash`。直接 API 和 Claude Code 非交互调用均成功，Claude 返回 `CLAUDE_OK`。
- OpenCode 1.17.18；使用 `@ai-sdk/openai-compatible`、DeepSeek OpenAI 兼容端点和 `deepseek-v4-flash`。直接 OpenAI API 返回 200，但 OpenCode 在该麒麟环境中停在自身 `init` 阶段，未发出 provider 请求，90/120 秒超时。

## Skill 安装

`skillctl` 从 `origin/main` 安装，Forgejo 使用独立只读 token。`skillctl doctor` 的 Python、uv、Forgejo、token、devpi、Claude/OpenCode 目录检查全部通过。

执行：

```text
skillctl install e2e-1783909061/native-1783909061@1.0.0 \
  --target claude --target opencode
```

安装成功，Release checksum 与锁文件 checksum 一致。中立目录为 `~/.skillify/skills/e2e-1783909061/native-1783909061`；Claude 和 OpenCode 投影均为指向该目录的符号链接。Claude Code 实际调用 Skill 工具并读取到标题 `Native`。

OpenCode 官方全局 Skill 路径为 `~/.config/opencode/skills/<name>`，且目录必须匹配 frontmatter name；项目原占位路径已修正。不同 namespace 的同名 Skill 在 OpenCode 全局目录会冲突，后续需设计明确的冲突策略。

## 结论

Skillify 下载、校验、锁定和双 Agent 投影链路通过；Claude Code 模型与 Skill 实际读取通过。OpenCode 已安装、provider 与 Skill 文件均配置正确，但其客户机运行时初始化阻塞尚未解决，因此 OpenCode 的最终模型读取 Skill 结论为未通过。
