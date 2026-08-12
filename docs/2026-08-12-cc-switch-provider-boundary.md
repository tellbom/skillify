# CC Switch / Provider 配置职责边界

## 结论

Skillify 只托管任务，不托管模型供应商配置。默认官方 Agent Host 中，OpenCode 与
Claude Code 都使用各自原生配置；CC Switch 可负责 Claude 的模型端点、Key、模型映射与
协议转换。

## 职责划分

| 组件 | 负责 | 不负责 |
|---|---|---|
| Skillify Web | 下发任务、展示事件与决策、发出取消意图 | 模型配置、协议转换、直接杀进程 |
| `skillctl agent bridge` | 绑定工作区、拉取任务、启动/取消 Provider Session、回传事件 | API Base URL、模型名、模型 Key、CC Switch 生命周期 |
| Agent Host | 调用官方 SDK、注入批准的 MCP、恢复 Session、转发交互 | 覆盖 Provider 模型配置 |
| Claude Code / CC Switch | 模型选择、认证、端点、Anthropic/OpenAI 协议适配 | Skillify 任务权限、MCP 范围、Web 决策与任务 Gate |
| OpenCode | 自身 Provider、模型与凭据配置 | Skillify 控制面与任务治理 |

## 端侧使用

1. 在运行 Bridge 的同一系统账户中启动 CC Switch，启用 Claude 接管或本地代理。
2. 先在端侧终端运行 `claude -p "ping"`，确认 Claude Code 自身可以完成请求。
3. 运行 `skillctl agent bridge start`，不再加载 Skillify 模型 `.env`。
4. 在 Web 下发 Claude Code 任务；Skillify 继续负责 MCP、Web 决策、取消与最终 Gate。

Claude Agent SDK 默认不加载文件系统配置，因此 Agent Host 显式启用 `user`、`project`
和 `local` 三类 Claude Code 原生设置源。启动命令协议不再包含 `model` 或模型环境字段。

旧 `~/.skillctl/settings.json` 中的模型字段不会影响默认官方 Host；它们仅用于显式启用的
legacy Shogun 兼容路径。当前改造不包含 CC Switch 安装、启动、健康检查或自动切换。
