# Skillify Code Map 可视化收敛方案方向 Brief

> 日期：2026-07-19
> 用途：交付 Claude Opus，据此生成正式 Plan 与 Task 节点；再交付 Codex 评审和实施。
> 文档性质：架构方向与裁决，不是实施计划，不代表任务已经完成。

## 1. 背景与本轮裁决

Skillify 的 Code Map 不是一个单纯的展示页面。它承担代码索引、符号关系、调用关系、增量更新以及 Agent 精确检索，属于代码开发 Agent 的核心底座，必须保留。

本轮只补回“面向人的代码可视化能力”。不再由 Skillify 重复开发一套完整图形引擎，而是优先接入成熟 GitHub 项目的原生可视化界面。Skillify 提供入口、数据适配、只读约束和生命周期管理。

最终边界：

1. Skillify Code Map 是唯一代码图谱真源（Source of Truth）。
2. Agent、MCP 和 Workflow 继续只查询 Skillify Code Map/CodeGraph 核心接口。
3. 外部可视化项目只服务人类浏览，不参与 Agent 上下文组装和任务决策。
4. 外部项目不得成为第二套生产索引真源，也不得反向修改源码。
5. 不再兼容 Chrome 102。使用可视化功能的端侧必须安装满足构件清单要求的 Chrome。
6. 浏览器版本不足只阻断可视化，不能阻断 Code Map 索引、Agent 执行、MCP 查询或其他 Skillify 功能。
7. 不做 A/B 双实现，不保留原有自研 Code Map 前端作为长期备用方案。

## 2. 目标与非目标

### 2.1 目标

- 用户可以从 Skillify 项目/工作区入口启动代码地图可视化。
- 用户查看目录、文件、符号、依赖、调用关系和热点指标，并能快速定位到源码位置。
- 可视化数据来自现有 Code Map 核心的稳定导出协议。
- 可视化程序在端侧、本地、离线、只读运行。
- 最大程度复用上游项目的原生界面和交互，不在 Skillify 内复刻同类页面。
- 可视化组件可以被替换，而不影响 Agent 和 Code Map 核心协议。

### 2.2 非目标

- 不通过可视化界面编辑、重命名、删除、生成或提交代码。
- 不通过可视化界面执行 Shell、Git push、Agent 或 Workflow。
- 不将可视化项目的 AI Chat、MCP、Skill、Hook 或代码修改能力一并引入。
- 不建设服务器沙箱或服务器端代码分析环境。
- 不将源码上传服务器或外部服务。
- 不为了嵌入效果重写上游项目的主要前端。
- 不维护两套独立的 Code Map 索引和查询语义。

## 3. 总体架构

```text
Skillify Web/CLI 入口
        |
        v
端侧 Visualization Launcher
        |
        +--> 浏览器版本门禁
        +--> Workspace 授权与只读边界
        +--> Code Map Graph Export
        +--> Visualizer Adapter/Converter
        +--> 启动上游原生 Web Runtime
        +--> localhost 地址或本机打开浏览器

Agent / MCP / Workflow
        |
        +--> Skillify Code Map Query API（与可视化隔离）
```

可视化链路只能读取 Code Map 导出产物。可视化进程崩溃、浏览器不兼容或用户未安装可视化构件时，Code Map 核心和 Agent 链路仍须正常运行。

## 4. 唯一数据真源与导出协议

### 4.1 核心原则

不得让外部可视化项目直接重新解析工作区后成为权威数据源。应由 Skillify Code Map 核心提供带版本的只读 Graph Export，再由薄 Adapter 转换成目标项目格式。

如果某个上游可视化项目必须运行自己的索引器才能显示，应满足以下限制之一：

- 其索引只作为临时展示缓存，不向 Agent/MCP 暴露；或
- 先开发从 Skillify Graph Export 到其输入格式的转换器，关闭其源码扫描；或
- 若两者都做不到，则该项目不符合接入条件。

### 4.2 建议的中立导出模型

```yaml
schema_version: codemap.graph/v1
repository:
  workspace_id: string
  revision: string
  generated_at: datetime
nodes:
  - id: stable-id
    kind: repository|module|directory|file|class|function|method|symbol
    name: string
    file: relative/path
    line_start: integer|null
    line_end: integer|null
    language: string|null
    metrics: object
edges:
  - source: node-id
    target: node-id
    kind: contains|imports|calls|inherits|implements|references
    weight: number|null
```

要求：

- Node ID 在同一 revision 中稳定。
- 文件路径只能是相对工作区路径，禁止泄露无关绝对路径。
- 导出格式必须有 `schema_version`。
- 大仓库支持分页、分片或流式生成，禁止要求 Web 前端一次载入无限制 JSON。
- 导出文件写入独立状态目录，不写入用户仓库。
- 增量索引仍由 Code Map 核心负责，可视化 Adapter 不复制增量算法。

## 5. 外部可视化项目选择策略

### 5.1 候选方向

#### GitNexus

优势：依赖图、符号和调用关系的交互表达更接近代码图谱需求，原生 Web 体验完整。

硬门禁：当前许可证为 PolyForm Noncommercial。普通企业内部使用不能仅因项目在 GitHub 开源就默认合规。只有法务确认适用，或取得商业授权后，才能将其作为默认可视化引擎。

接入时必须关闭或隔离其代码修改、AI Chat、MCP、Skill、Hook 和自有权威索引能力。

#### CodeCharta

优势：BSD-3-Clause、可完全本地运行、原生 3D Code City 与代码指标展示成熟，许可证风险较低。

限制：它更偏向代码指标、热点和城市视图，不等价于完整的符号调用图。必须先验证 Skillify Graph Export 到 `cc.json` 的转换能否覆盖实际用户场景。不能用漂亮的 3D 界面替代核心调用关系需求。

### 5.2 选择裁决流程

Opus 的 Plan 必须设置一个前置 Gate，而不是同时生产化两个引擎：

1. 许可证 Gate：企业内网使用、再分发、修改构建和离线镜像是否合法。
2. 数据 Gate：能否消费 Skillify Graph Export，是否会强迫形成第二真源。
3. 功能 Gate：是否覆盖目录、文件、符号、调用/依赖和热点中的目标集合。
4. 离线 Gate：断网、无 CDN、无遥测、无模型 API 时能否完整运行。
5. 浏览器 Gate：冻结版本在规定 Chrome 版本上通过真实端到端测试。
6. 安全 Gate：只读挂载后所有查看功能仍可用，不要求向仓库写文件。
7. 性能 Gate：在约定规模的真实仓库上达到首屏、交互和内存指标。

选择规则：

- GitNexus 只有许可证和能力隔离均通过时才优先采用。
- GitNexus 许可证未通过时，优先验证 CodeCharta。
- CodeCharta 若不能表达核心查看场景，必须回到候选调研，不得用美观性降低功能目标。
- 阶段一最终只能有一个默认引擎；其他候选不进入生产依赖和运维清单。

## 6. 浏览器支持与升级门禁

### 6.1 不再支持 Chrome 102

不为 Chrome 102 编写 polyfill、兼容构建或旧版前端分支，也不固定使用陈旧的上游版本来迁就 Chrome 102。

### 6.2 版本策略

不得长期写死一个未经验证的最低版本（例如仅凭框架文档写 `Chrome >= 111`）。每个冻结的可视化构件必须在离线清单中记录：

```json
{
  "visualizer": "selected-engine",
  "version": "pinned-version",
  "sha256": "artifact-sha256",
  "min_chrome_major": 0,
  "tested_chrome_majors": [],
  "graph_schema_versions": ["codemap.graph/v1"]
}
```

其中 `min_chrome_major` 只能来自真实兼容性测试。上游升级时必须重新验证并更新，不能自动继承旧结论。

### 6.3 用户体验

启动可视化前由端侧 Launcher 检测 Chrome：

- 满足版本：启动可视化并打开本地页面。
- 未安装：提示从内网软件源安装批准版本。
- 版本过低：明确显示当前版本、最低版本和内网升级指引，并阻断启动。
- 无法检测：允许用户运行诊断命令，但默认不绕过门禁。

Skillify 主页面不得因为可视化不兼容而白屏。入口可显示“浏览器需升级”，其他功能继续使用。

浏览器离线包、版本清单和 checksum 应通过 Forgejo/内部构件仓管理，禁止运行时访问公网下载安装。

## 7. 集成形式与生命周期

### 7.1 推荐入口

Web 项目页增加“打开代码地图”入口，但不在 Skillify 前端重写上游可视化组件。

端侧提供：

```bash
skillctl codemap visualize start --workspace <workspace-alias>
skillctl codemap visualize status --workspace <workspace-alias>
skillctl codemap visualize open --workspace <workspace-alias>
skillctl codemap visualize stop --workspace <workspace-alias>
skillctl codemap visualize doctor
```

### 7.2 页面承载方式

阶段一优先在新标签页打开上游原生页面，不使用 iframe。原因：

- 避免 CSP、跨域、Cookie 和路由冲突。
- 避免 Skillify 对上游布局和前端状态承担维护责任。
- 上游升级时减少耦合。

只有确认 iframe 的 CSP、安全、路由、资源路径和浏览器兼容性稳定后，后续阶段才可单独评审；不能作为阶段一隐含任务。

### 7.3 本机与远程浏览器约束

阶段一限定可视化程序和浏览器运行在代码工作区所在的同一台 Linux 端侧机器，服务只监听 `127.0.0.1`。

如果 Skillify Web 操作人员使用的是另一台电脑，不能把目标端点返回的 `127.0.0.1` URL 直接发给远程浏览器。远程代理、隧道或 LAN 暴露属于新的安全范围，阶段一不实现。

## 8. 只读和安全边界

“界面没有编辑按钮”不构成只读保证。必须采用不可绕过的运行边界：

1. 工作区必须通过 `workspace-alias`/`allowed_paths` 授权，解析 canonical path 并阻止软链接逃逸。
2. 可视化进程以普通用户运行，禁止 root。
3. 仓库目录采用 OS/容器只读挂载；无法只读挂载时使用只读快照作为输入。
4. 索引、转换产物、日志和 PID 写入 Skillify 独立状态目录。
5. 清理环境变量，不传递 Git 凭据、SSH Agent、数据库令牌、模型 Key 和其他秘密。
6. 默认断网；必须联网的能力不得进入阶段一。
7. 只监听 `127.0.0.1`，随机或受管端口，禁止 `0.0.0.0`。
8. 不执行上游的 setup、install skill、install hook、MCP 注册、rename、commit 或 push 能力。
9. 版本固定、checksum 校验、离线分发、SBOM 和许可证清单齐全。
10. Launcher 负责进程健康检查、重复启动去重、异常退出回收和 stop。
11. 服务端只接收生命周期事件和诊断摘要，不上传源码、图数据或源代码片段。

## 9. 性能与降级方向

Plan 必须先定义仓库规模分档和数据预算，建议至少覆盖：

- 小型：不超过 10,000 节点。
- 中型：约 50,000 节点。
- 大型：约 100,000 节点或由真实内网仓库确定上限。

必须验证：

- Graph Export 时间与增量刷新时间。
- 可视化首屏时间。
- 搜索/过滤/定位响应时间。
- 浏览器峰值内存和稳定运行内存。
- 断网后的静态资源完整性。
- GPU/WebGL 不可用时的明确报错或二维/列表降级。

对于超出上限的图，不允许无提示卡死浏览器。应支持按目录、模块、关系类型或深度裁剪，再生成可视化子图。

## 10. 建议的服务端事件

只上报生命周期和诊断，不上报代码内容：

```text
codemap.visualization.requested
codemap.visualization.browser_blocked
codemap.visualization.export_started
codemap.visualization.export_completed
codemap.visualization.started
codemap.visualization.ready
codemap.visualization.failed
codemap.visualization.stopped
```

事件字段只允许包含 endpoint、workspace ID、visualizer/version、Chrome major、耗时、节点/边数量和错误码。不得包含绝对路径、源码、查询结果和凭据。

## 11. Opus 生成 Plan/Task 时必须覆盖的工作包

Opus 应把以下内容拆成可验收节点，但不要把调研结果直接标记为实现完成：

1. 现有 Code Map 核心能力与 API 基线核实。
2. 自研旧 Code Map 前端代码清单和一次性删除/迁移计划。
3. GitNexus/CodeCharta 许可证、离线、数据模型、只读和浏览器 Spike。
4. 单一可视化引擎选择 Gate 与签字结论。
5. `codemap.graph/v1` Schema、版本策略和兼容规则。
6. Code Map Graph Export 实现。
7. 单一 Visualizer Adapter/Converter。
8. 离线构件 manifest、checksum、SBOM 和 Forgejo 分发。
9. 端侧 Launcher 的 start/status/open/stop/doctor。
10. Chrome 版本检测、阻断页和内网升级指引。
11. workspace 只读、凭据清理、localhost 和断网约束。
12. Skillify Web 的薄入口、状态展示和错误提示。
13. 端侧生命周期事件和服务端只读状态展示。
14. 小/中/大型仓库的性能、内存和裁剪策略。
15. Chrome 真实版本 E2E、断网测试、只读攻击测试和失败恢复。
16. 文档、运维手册、升级/回滚和已知限制。
17. 最终删除旧前端及无用依赖，确保不存在双实现。

## 12. Plan/Task 的强制验收原则

- 每个“完成”节点必须指向实现文件、测试或可复现命令，禁止只凭文档勾选。
- 必须有真实链路验收：选择工作区 → 导出 → 转换 → 启动 → 浏览器打开 → 交互查看 → 停止。
- 必须证明 Agent/MCP 查询不依赖可视化进程。
- 必须证明可视化进程无法写入源码目录。
- 必须在完全断网环境运行。
- 必须使用真实 Chrome 构建版本测试，不能只用当前 Playwright 最新 Chromium 推断兼容性。
- 必须测试 Chrome 版本过低时只阻断可视化、不影响其他功能。
- 必须证明服务只监听 localhost。
- 必须证明没有携带 Git、SSH、模型或业务系统凭据。
- 必须验证升级失败时可以回滚到上一份冻结构件和 Adapter。
- 最终仓库不得保留旧自研前端与新外部界面的两套生产入口。

## 13. NO-GO 条件

出现任一情况，应停止生产接入而不是降低要求：

- 许可证不允许目标组织内部使用、修改或再分发。
- 外部项目必须把源码上传公网或依赖外部 CDN/API。
- 无法关闭写代码、Shell、Git、Hook、Skill 或 MCP 修改能力。
- 无法使用只读工作区正常运行。
- 必须成为第二套 Agent 代码索引真源。
- 无法消费或可靠转换 Skillify Graph Export。
- 在批准 Chrome 版本与目标仓库规模上无法稳定运行。
- 为了展示美观必须削弱 Code Map 核心、Agent 检索或安全边界。

## 14. 最终推荐结论

批准恢复 Code Map 可视化，但按“核心保留、展示外置、单一真源、端侧只读、版本门禁”实施。

技术选型不以界面美观作为唯一依据：GitNexus 的图谱交互更匹配，但必须先过许可证和能力隔离 Gate；未通过则验证 BSD-3-Clause 的 CodeCharta。阶段一只生产化一个引擎。

不再兼容 Chrome 102。可视化构件清单声明并检测经过真实测试的最低 Chrome 主版本；用户从内网批准源升级后才能使用可视化。该门禁不得影响 Code Map 核心和 Agent 开发链路。
