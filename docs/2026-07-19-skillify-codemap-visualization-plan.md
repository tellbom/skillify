# Skillify 人用代码可视化集成 · 实施计划（边界修正版）

> 日期：2026-07-19
> 配套任务：`docs/2026-07-19-skillify-codemap-visualization-task.md`
> 交付对象：Codex 核实官方 GitHub 项目后连续实施。
> 状态：用户接受个人非商业使用边界后，GitNexus 受限通过 G1；P2–P4 已实现，P5 开发期验证部分完成，P6 待测试环境。

## 0. 本轮纠正

当前 Skillify 已经集成外部开源 `colbymchenry/codegraph v0.9.6`：

- CodeGraph 负责 Agent 使用的代码索引；
- Agent 通过 `codegraph serve --mcp` 和 `codegraph_explore` 使用它；
- Skillify 只维护其离线构件、校验、初始化、同步和 MCP 配置；
- 当前没有面向用户的 Code Map 前端。

本轮需求不是扩展或替换 CodeGraph，也不是把 CodeGraph 数据导出给前端。本轮只增加一款“供用户查看代码关系”的外部可视化工具。

因此删除此前方案中的以下内容：

- 不研究 CodeGraph 内部解析器、图数据库和私有索引格式；
- 不从 CodeGraph 构建 `codemap.graph/v1`；
- 不开发 CodeGraph Graph Export；
- 不开发 CodeGraph → Visualizer Adapter；
- 不要求可视化项目关闭自己的只读扫描器；
- 不因为可视化需要修改 `codegraph.py`、MCP 配置、Agent 查询或索引语义。

## 1. 最终架构边界

```text
Agent / OpenCode / Claude Code
        |
        +--> CodeGraph v0.9.6 + MCP（现状，完全不动）

用户 Web/CLI 入口
        |
        +--> Endpoint Bridge
                |
                +--> 外部 Visualizer 原生程序
                        +--> 只读扫描工作区/只读快照
                        +--> 独立展示索引与状态目录
                        +--> localhost 原生 Web UI
                        +--> 本机 Chrome
```

允许出现两份物理索引，但它们不是两套 Agent 真源：

- `.codegraph/`：Agent 专用，保持现状；
- Visualizer index：只供用户界面查看，不能接入 Agent、MCP、Workflow 或上下文检索。

这是合理隔离，不属于重复实现，因为第二份索引由成熟外部项目自行维护，Skillify 不重写其图算法和前端。

## 2. 交付目标

用户可以从 Skillify 或 CLI 启动端侧代码可视化，查看：

- 目录和文件结构；
- 类、函数、方法等符号；
- 调用和依赖关系；
- 点击节点查看或定位相对文件路径与行号；
- 搜索、过滤、缩放和关系导航。

阶段一不接受只有目录、指标或代码城市而没有调用/依赖导航的半成品。

## 3. 非目标和红线

- 不修改 `src/skillify/agent/codegraph.py`。
- 不修改 OpenCode/Claude Code 的 CodeGraph MCP 配置。
- 不修改 `codegraph init/sync/serve --mcp` 行为。
- 不让 Visualizer 的索引或查询进入 Agent、MCP、Workflow。
- 不开发自己的图渲染页面。
- 不把代码上传服务器、公网或第三方服务。
- 不启用上游项目的 AI Chat、改码、rename、Shell、Git、Hook、Skill、MCP 工具。
- 不建设服务器沙箱和服务器端代码分析。
- 不使用 iframe；阶段一打开上游原生页面。
- 不兼容 Chrome 102；用户使用可视化前必须升级到 manifest 声明的版本。

## 4. 证据规则：克隆官方源码后判断

Codex 不得依赖模型记忆、搜索摘要、宣传页面或 README 单独下结论。开发环境允许联网从官方 GitHub 拉取候选仓库，但最终内网运行必须完全断公网。

每个候选必须记录：

```text
official_url
remote.origin.url
commit_sha
tag/version
license_file + sha256
dependency_lockfiles
build command + output
runtime command + output
```

候选只 clone 到临时评估目录。选定前不加入 Skillify、不创建 submodule、不提交候选源码。

## 5. 当前 Skillify 基线核实

Codex 首先在真实仓库确认：

- CodeGraph manifest 确实锁定 v0.9.6 及其官方 URL/checksum；
- `codegraph.py` 只是生命周期适配；
- OpenCode/Claude Code 通过 MCP 使用 CodeGraph；
- 当前没有 Code Map 前端；
- Endpoint Task、Bridge、Outbox、Web 项目页、CLI、数据库迁移的准确文件和现状；
- 当前工作树中的用户改动和项目测试命令。

该核实只用于保护边界，不要求 clone 或研究 CodeGraph 上游源码。完成后建立“禁止触碰文件/行为清单”和回归测试基线。

## 6. 外部可视化项目选型

### 6.1 Codex 必须下载的官方 GitHub 候选

阶段一只评测以下三个明确候选。Codex 必须从列出的官方 URL clone 源码，不能用搜索结果中的 fork、镜像、二进制转载站或同名项目代替：

| 顺序 | 项目 | 官方 GitHub | 评测定位 | 进入生产的前提 |
| --- | --- | --- | --- | --- |
| 1 | GitNexus | `https://github.com/abhigyanpatwari/GitNexus.git` | 功能和交互标杆：验证符号、调用、依赖、源码定位和原生 Web UI | PolyForm Noncommercial 默认不能进入生产；只有获得明确适用于目标组织、长期离线且无联网校验的商业授权才可选 |
| 2 | CodeCompass | `https://github.com/Ericsson/CodeCompass.git` | 完整代码理解 Web 工具候选：重点验证目标语言、部署复杂度、只读扫描和 GPLv3 分发义务 | 功能、语言、完全离线、只读和许可证政策全部通过 |
| 3 | Emerge | `https://github.com/glato/emerge.git` | 轻量 MIT 候选：重点验证是否真正达到符号级 calls、依赖和源码行号定位，而不是只有文件/实体依赖图 | 必须完整达到阶段一功能底线；不能以许可证宽松为由接受功能降级 |

下载评测顺序固定为 GitNexus → CodeCompass → Emerge，但最终选择不是按顺序直接采用，而是逐个完成同一 Gate 后比较。GitNexus 即使许可证失败，也要保留为功能/交互基准；不得把其代码或受限构件带入生产包。

Codex 可以在三个候选全部失败后提出新增候选，但必须先提交失败证据并获得用户确认，不能自行无限扩展调研范围。

以下项目阶段一不再下载评测：

- CodeCharta：偏指标/城市视图，不能满足调用图底线；
- OpenGrok：偏代码搜索和交叉引用，不是目标交互调用图；
- dependency-cruiser：偏 JS/TS 模块依赖，语言和符号层级不足；
- go-callvis：仅 Go；
- Sourcetrail/NumbatUI：桌面方向、维护和分发边界不符合本阶段 Web 入口目标。

### 6.2 允许自带扫描和独立索引

外部项目可以使用自己的解析器扫描代码，因为它只负责人用展示。必须满足：

- 输入是只读工作区或只读快照；
- 索引写入 Skillify 独立状态目录，不写仓库；
- 其扫描/索引结果不接入 Agent 和 MCP；
- 停止或删除 Visualizer 不影响 CodeGraph 和 Agent。

无需把 CodeGraph 数据转换成外部项目格式。这正是直接复用成熟项目、避免重复开发的核心。

### 6.3 硬 Gate

候选必须全部通过：

1. **功能**：真实仓库能显示目录、文件、符号、调用、依赖和文件/行号定位。
2. **原生复用**：直接启动其正式 Web/CLI/Server，不重写界面。
3. **完全离线**：运行不依赖 CDN、公网 API、遥测、模型服务、在线激活或周期授权。
4. **只读**：在只读代码输入下完整工作；所有索引和缓存可重定向到独立状态目录。
5. **安全**：能关闭 AI Chat、代码修改、Shell、Git、Hook、Skill、MCP 等非展示能力。
6. **许可证**：允许目标组织内部使用和端侧分发。PolyForm Noncommercial 默认不通过，除非取得书面、长期有效且不需要联网校验的商业授权。其他许可证以锁定 commit 的原文和实际分发方式评估。
7. **浏览器**：冻结版本在真实 Chrome 上通过，得到 `min_chrome_major`。
8. **性能**：在目标规模下达到 §11 预算。

全部候选失败时 NO-GO，不提交半成品页面。

### 6.4 选择后连续开发

选出唯一引擎并形成 commit 级证据后，Codex直接继续集成。只有需要购买授权、接受新的许可证义务或全部候选失败时才请求用户决定。

## 7. 只读工作区模型

优先级：

1. 将真实工作区以只读方式挂载给 Visualizer；
2. 若上游会尝试在仓库写索引，改用只读快照；
3. 所有索引、缓存、日志、PID、临时文件写入：

```text
<skillify-state>/codemap-visualizer/<workspace-id>/<engine-version>/
```

只读不能依赖“界面没有编辑按钮”，必须由 OS/容器文件系统边界保证。必须校验 canonical path、allowed_paths 和软链接逃逸。

## 8. 完全断网和运行隔离

可视化运行必须由端侧强制隔离：

- 首选目标环境已有的 rootless Podman/Docker：网络 `none`、工作区 `ro`、独立状态目录 `rw`；
- 或使用目标 Linux 已批准的 bubblewrap/systemd/unshare 网络命名空间；
- 不能仅通过设置 `NO_TELEMETRY` 等环境变量声称断网。

同时要求：

- 普通用户运行；
- 清除 Git、SSH、数据库、模型和业务系统凭据；
- 服务只监听 `127.0.0.1`；
- 不执行运行时安装、npm 下载或 GitHub 拉取；
- 无强制隔离能力时 `doctor` 阻断启动。

开发阶段从 GitHub 拉取并构建后，将源码/构件、依赖和静态资源固定并镜像到 Forgejo/内部构件仓。端侧安装和运行只访问内网。

## 9. Web → Bridge → Visualizer

```text
Skillify Web
  → 创建 codemap.visualization.start/stop/open/status Endpoint Task
  → 端侧 Bridge pull/ack
  → Bridge 调用本机 Launcher
  → Launcher 创建只读运行环境并启动 Visualizer
  → 端侧 xdg-open/批准 Chrome 打开 localhost
  → 事件经 Outbox 回传
  → Web 只显示状态和错误
```

中央 Web 不访问端点 localhost，也不向远程浏览器返回 localhost URL。浏览器、Visualizer 和代码工作区必须位于同一台 Linux Endpoint。

Codex必须先核实当前 Endpoint Task 链。如果 pull/ack/lease/cancel/events 有缺口，复用现有协议补齐最小链路，不创建第二套通讯协议。

## 10. CLI、Chrome 和构件 manifest

CLI：

```text
skillctl codemap visualize start --workspace <alias>
skillctl codemap visualize status --workspace <alias>
skillctl codemap visualize open --workspace <alias>
skillctl codemap visualize stop --workspace <alias>
skillctl codemap visualize doctor
```

manifest 至少包含：

```text
engine
official_url
commit_sha
tag/version
artifact_sha256
license_sha256
sbom
runtime_command
min_chrome_major
tested_chrome_majors
isolation_backend requirements
```

Chrome 最低版本在候选 Spike 中用真实二进制测试得出。Launcher 检测不达标时只阻断可视化，并显示当前版本、最低版本和内网升级指引；不得影响 Agent/CodeGraph。

## 11. 性能预算

| 规模 | 首次可交互 | 搜索/过滤 P95 | 峰值内存 | 要求 |
| --- | ---: | ---: | ---: | --- |
| ≤10k nodes | ≤5s | ≤1s | ≤1.5GiB | 完整图 |
| ≤50k nodes | ≤15s | ≤2s | ≤3GiB | 完整图或可靠分片 |
| ≤100k nodes | ≤30s | ≤3s | ≤4GiB | 允许按模块/深度裁剪，不能卡死 |

如果上游引擎无法提供统一 node 数，应记录其可比规模指标（文件数、符号数、边数）和换算方式。超限必须明确提示，不能让浏览器无提示卡死。

## 12. 生命周期事件

```text
codemap.visualization.requested
codemap.visualization.browser_blocked
codemap.visualization.scan_started
codemap.visualization.scan_completed
codemap.visualization.started
codemap.visualization.ready
codemap.visualization.failed
codemap.visualization.stopped
```

只允许 Endpoint/workspace ID、引擎版本、Chrome major、耗时、文件/符号/边数量和错误码。禁止绝对路径、源码、索引内容、查询结果和凭据。

## 13. 实施顺序

```text
P0 Skillify 与通讯链基线
 → P1 官方可视化仓库 Clone/Build/Run Spike
 → G1 唯一引擎或 NO-GO
 → P2 冻结离线构件
 → P3 只读隔离 Launcher + CLI
 → P4 Bridge/Endpoint Task/Web 薄入口
 → P5 开发环境完整验证
 → P6 真实内网终验和回滚
```

G1 通过后 Codex连续推进，不需要再等待计划重写。真实环境暂时不可用时，只能标记 `implemented/dev_verified`，不能虚假标记 `env_verified`。

## 14. 核心保护验收

最终必须证明：

- `codegraph.py`、CodeGraph manifest、OpenCode/Claude Code MCP 配置没有因为可视化被修改；
- CodeGraph init/sync/MCP/Agent 查询回归通过；
- 关闭、卸载或破坏 Visualizer 后 Agent 仍正常使用 CodeGraph；
- Visualizer 索引目录不被 Agent、MCP 或 Workflow 引用；
- 可视化启动前后用户工作区无写入变化。

## 15. NO-GO

- 没有成熟候选同时满足调用/依赖/定位；
- 必须连接公网、CDN、模型或在线授权；
- 无法在只读输入下工作；
- 无法关闭改码、Shell、Git、Hook、Skill、MCP；
- 许可证不允许目标内部使用/分发；
- 无法由 OS/容器强制断网；
- 只能通过修改 Agent CodeGraph 核心才能接入；
- 在批准 Chrome 和目标规模下不稳定。

NO-GO 时提交源码级证据，不留下半成品生产入口。
