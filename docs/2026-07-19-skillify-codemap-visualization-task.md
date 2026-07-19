# Skillify 人用代码可视化集成 · 任务清单（边界修正版）

> 配套计划：`docs/2026-07-19-skillify-codemap-visualization-plan.md`
> 执行：Codex。
> 原则：Agent CodeGraph v0.9.6 完全保持现状；本任务只集成独立、只读、完全离线的外部可视化项目。

## 全局红线

- 不修改 `src/skillify/agent/codegraph.py`。
- 不修改 CodeGraph manifest、init/sync、MCP Server 和 `codegraph_explore` 语义。
- 不修改 OpenCode/Claude Code 的 CodeGraph MCP 配置。
- 不开发 CodeGraph Graph Export、`codemap.graph/v1` 或转换器。
- 外部 Visualizer 允许自行只读扫描代码，但其索引只供人看，禁止进入 Agent/MCP/Workflow。
- 不用模型记忆、搜索摘要或 README 单独替代官方源码和真实运行证据。
- 不提交只有目录/指标而缺少调用、依赖和定位的半成品。

状态：P0 已完成；P1/G1 为 NO-GO；P2–P6 因 Gate 阻断未启动。`implemented / dev_verified / env_verified` 分开记录。

---

## P0 · 当前仓库与通讯链基线

### T0.1 真实源码路径和核心保护基线

- **动作**：读取适用 `AGENTS.md`，检查工作树；用 `rg --files` 定位 CodeGraph manifest、`codegraph.py`、OpenCode/Claude Code 配置、Bridge、Endpoint Task、Outbox、CLI、Web 项目页、API Client、ORM/迁移和测试命令。
- **确认**：CodeGraph v0.9.6 来源、checksum、生命周期和 MCP 接法；当前没有 Code Map 前端。
- **产物**：`docs/assessments/2026-07-19-codemap-visualizer-baseline.md`，列出准确路径和禁止触碰清单。
- **验证**：记录 CodeGraph init/sync/MCP/Agent 现有回归命令；记录用户未提交改动和原始测试失败。
- **Gate**：后续不得使用通配占位路径；不得覆盖无关用户改动。
- **状态**：implemented / dev_verified。

### T0.2 Endpoint Task/Bridge/Events 链路

- **依赖**：T0.1。
- **动作**：从 Web 任务创建追踪到服务端持久化、pull/ack/lease/cancel、Bridge dispatch、Outbox 和事件接收，运行现有契约测试。
- **产物**：在基线报告加入准确时序、payload、Endpoint 身份和缺口。
- **Gate**：缺失能力列入 T4.1，用现有协议最小补齐；禁止新建第二套轮询/事件协议。
- **状态**：implemented / dev_verified。

---

## P1 · 官方 GitHub 可视化项目选型

### T1.1 官方仓库 Clone 和身份记录

- **依赖**：T0.1。
- **评测清单与顺序**：

```text
1. https://github.com/abhigyanpatwari/GitNexus.git
2. https://github.com/Ericsson/CodeCompass.git
3. https://github.com/glato/emerge.git
```

- **动作**：逐个 clone 到仓库外临时目录；确认 `remote.origin.url`，记录首次评测 commit，再根据官方 tag/release 选择一个明确 commit 作为冻结评测版本。
- **建议命令形态**（临时目录按实际环境填写，不把候选 clone 到 Skillify 仓库）：

```bash
git clone --filter=blob:none https://github.com/abhigyanpatwari/GitNexus.git <tmp>/GitNexus
git clone --filter=blob:none https://github.com/Ericsson/CodeCompass.git <tmp>/CodeCompass
git clone --filter=blob:none https://github.com/glato/emerge.git <tmp>/emerge
git -C <candidate> remote get-url origin
git -C <candidate> rev-parse HEAD
git -C <candidate> tag --points-at HEAD
```

- **每个候选记录**：official URL、commit SHA、tag/version、LICENSE+SHA256、锁文件、维护时间、构建命令和运行入口。
- **禁止**：把搜索摘要当证据；直接以最新 main 代表冻结版本；选定前加入 submodule/vendor。
- **候选定位**：
  - GitNexus：功能/交互标杆；许可证未取得离线商业授权时只能评测，不能进入生产构件；
  - CodeCompass：完整 Web 代码理解候选；必须验证目标语言、部署复杂度、只读和 GPLv3 实际义务；
  - Emerge：MIT 轻量候选；必须证明是符号级调用/依赖/行号定位，不能只有文件或实体依赖图。
- **不下载清单**：CodeCharta、OpenGrok、dependency-cruiser、go-callvis、Sourcetrail/NumbatUI。本阶段不得自行重新加入。
- **扩展规则**：只有三个候选全部失败并提交逐项证据后，才可请求用户批准新增候选；Codex 不得自行无限搜索项目。
- **产物**：`docs/assessments/2026-07-19-codemap-visualizer-selection.md`。

### T1.2 源码审计、构建和完全离线运行

- **依赖**：T1.1。
- **源码检查**：外部 URL/CDN、telemetry、analytics、fetch/WebSocket、模型 API、在线授权、运行时下载、Shell/Git/写代码、Hook/Skill/MCP、索引目录配置、监听地址和 Chrome 构建目标。
- **真实运行**：
  - 使用代表性多语言仓库；
  - 将工作区只读挂载或制作只读快照；
  - 将索引/缓存重定向到独立状态目录；
  - 强制断网启动；
  - 真实 Chrome 打开原生页面；
  - 验证目录、文件、符号、calls、依赖、文件和行号定位；
  - 监测端口、网络请求和文件写入；
  - 测量小规模性能。
- **许可证**：以锁定 commit 原文评估内部使用和端侧分发。PolyForm Noncommercial 默认失败，除非已有符合要求的离线商业授权；其他许可证按实际义务记录。
- **Gate**：任何功能、离线、只读、安全、许可证、Chrome、性能硬项失败则候选出局。

### T1.3 G1 唯一引擎

- **依赖**：T1.2。
- **必须确定**：唯一引擎、commit/tag、构建和运行命令、扫描命令、索引目录参数、关闭非展示能力的方法、Chrome 最低版本、静态资源、许可证义务、性能数据。
- **通过**：Codex不暂停，继续 P2–P5。
- **需用户决定**：购买授权或接受新的许可证义务。
- **全部失败**：NO-GO，提交证据，不实现生产入口。
- **状态**：implemented / dev_verified。

---

## P2 · 冻结和镜像单一外部引擎

### T2.1 离线构件 manifest、SBOM 和复现

- **依赖**：G1。
- **实现**：复用项目已有离线 manifest/校验原语，固定 engine、official URL、commit、tag/version、artifact SHA256、LICENSE SHA256、SBOM、runtime/scan command、`min_chrome_major`、`tested_chrome_majors` 和 isolation requirements。
- **静态资源检查**：字体、图标、JS、CSS、WASM 等全部本地化；禁止运行时 npm/GitHub/CDN 下载。
- **分发**：准备 Forgejo/内部构件仓镜像和回滚材料，不让最终 Endpoint 访问 GitHub。
- **测试**：manifest Schema、checksum、许可证文件、完整性和版本回滚。
- **状态**：implemented / dev_verified；真实内部镜像补 env_verified。

---

## P3 · 只读隔离 Launcher、Chrome 门禁和 CLI

### T3.1 Visualizer 生命周期

- **依赖**：T2.1。
- **预期新增**：隔离的 visualizer 模块；准确目录和注册文件以 T0.1 为准。
- **先失败测试**：install/verify/scan/start/status/open/stop；重复启动幂等；健康检查；异常回收；版本不符和构件损坏。
- **输入**：只读工作区或只读快照。
- **输出**：`<skillify-state>/codemap-visualizer/<workspace-id>/<engine-version>/`，不得写仓库。
- **状态**：implemented / dev_verified / env_verified。

### T3.2 强制断网、无凭据和 localhost

- **依赖**：T3.1。
- **实现**：依据目标 Linux 已有能力，使用 rootless 容器 `network=none` 或批准的网络命名空间工具；无强制 Backend 时阻断启动。
- **先失败测试**：
  - 工作区只读、状态目录可写；
  - 软链接和 canonical path 不能逃逸 allowed_paths；
  - 引擎无法联网；
  - 仅监听 `127.0.0.1`，拒绝 `0.0.0.0`；
  - 清除 Git/SSH/DB/模型/业务凭据；
  - 普通用户运行；
  - AI Chat、改码、Shell、Git、Hook、Skill、MCP 均不可用。
- **完成证据**：启动前后工作区状态/哈希不变，网络探测失败，环境变量 allowlist。

### T3.3 Chrome 门禁和 CLI

- **依赖**：T3.2。
- **命令**：

```text
skillctl codemap visualize start --workspace <alias>
skillctl codemap visualize status --workspace <alias>
skillctl codemap visualize open --workspace <alias>
skillctl codemap visualize stop --workspace <alias>
skillctl codemap visualize doctor
```

- **Chrome**：按 manifest 检测。未安装/过低/不可检测时只阻断可视化并给内网升级指引；不得影响 CodeGraph/Agent。
- **open**：在代码所在 Endpoint 本机打开批准 Chrome/`xdg-open`，不把 localhost URL交给中央 Web 浏览器。
- **测试**：workspace alias、授权、浏览器全部分支、状态和错误码。

---

## P4 · 复用 Bridge 与 Web 薄入口

### T4.1 Endpoint Task 和 Bridge dispatch

- **依赖**：T0.2、T3.3。
- **实现**：在现有任务协议增加 `codemap.visualization.start|stop|open|status`。如果 T0.2 发现 pull/ack/lease/cancel/events 缺口，在现有协议中补齐最小必要部分。
- **payload allowlist**：Endpoint ID、workspace alias、动作、幂等键和批准的显示/裁剪参数；禁止绝对路径、Shell 和任意命令参数。
- **行为**：Bridge 调用本机 Launcher；中央服务不代理源码和可视化页面。
- **测试**：身份、授权、幂等、重试、租约、超时、取消、Bridge 重启、Outbox 重放和错误脱敏。

### T4.2 生命周期事件

- **依赖**：T4.1。
- **事件**：requested、browser_blocked、scan_started、scan_completed、started、ready、failed、stopped。
- **字段 allowlist**：Endpoint/workspace ID、引擎版本、Chrome major、耗时、文件/符号/边数、错误码和时间戳。
- **禁止**：绝对路径、源码、索引数据、查询结果、环境变量和凭据。
- **实现**：复用项目现有 ORM/迁移机制，不预设直接添加某个 SQL 文件。

### T4.3 Web 薄入口

- **依赖**：T4.2。
- **准确文件**：使用 T0.1 解析出的项目页、API Client、路由和测试位置。
- **实现**：启动、停止、状态、Chrome 升级提示和诊断错误。
- **禁止**：iframe、复制上游界面、返回 Endpoint localhost URL、上传源码。
- **测试**：Bridge 离线、Chrome 过低、构件缺失、扫描失败、启动成功；主页面和 Agent 功能始终正常。

---

## P5 · 开发验证

### T5.1 完整链路

- **依赖**：T4.3。
- **链路**：Web → Endpoint Task → Bridge → 只读扫描 → 独立索引 → 强制断网启动 → 本机 Chrome → 查看目录/文件/符号/calls/依赖/行号 → stop → 事件回传。
- **要求**：必须使用选定的真实引擎，不得以 fake 引擎代替终链。
- **回归**：CodeGraph init/sync/MCP、OpenCode/Claude Code 配置和 Agent 查询全部保持原状。
- **隔离证明**：删除 Visualizer 索引或停止进程后 Agent 仍正常；Agent/MCP 不引用 Visualizer 目录。
- **安全**：工作区前后无变化、无公网连接、仅 localhost、无凭据、路径逃逸失败。
- **性能**：按计划预算记录硬件、Chrome、文件/符号/边数、首屏、P95 和峰值内存。
- **产物**：`docs/testing/2026-codemap-visualizer-dev-verification.md`。
- **Gate G2**：全部通过才能标记 `dev_verified`。

---

## P6 · 真实内网终验

### T6.1 完全断网、升级和回滚

- **依赖**：G2。
- **环境**：真实内网 Linux Endpoint、真实 Server/Bridge、批准 Chrome、内部 Forgejo/构件仓，公网物理或策略断开。
- **验证**：安装、扫描、启动、查看、停止、重启；旧 Chrome 阻断；工作区只读攻击；DNS/HTTP 出网失败；大小仓库；Bridge 断线重放；构件升级失败回滚；Visualizer 崩溃/卸载时 Agent CodeGraph 正常。
- **产物**：`docs/testing/2026-codemap-visualizer-env-verification.md`。
- **Gate G3**：全部通过才标记 `env_verified`。暂时没有真实环境时保持 pending，不虚假勾选。

---

## 执行看板

- [x] T0.1 Skillify 基线与核心保护
- [x] T0.2 通讯链
- [x] T1.1 官方候选仓库身份
- [x] T1.2 源码/构建/断网 Spike
- [x] T1.3 唯一引擎 / G1（NO-GO：三个计划内候选全部失败）
- [ ] T2.1 冻结离线构件（G1 NO-GO，未启动）
- [ ] T3.1 生命周期（G1 NO-GO，未启动）
- [ ] T3.2 只读/断网/无凭据（G1 NO-GO，未启动）
- [ ] T3.3 Chrome/CLI（G1 NO-GO，未启动）
- [ ] T4.1 Bridge dispatch（G1 NO-GO，未启动）
- [ ] T4.2 事件（G1 NO-GO，未启动）
- [ ] T4.3 Web 入口（G1 NO-GO，未启动）
- [ ] T5.1 Dev 终链 / G2（G1 NO-GO，未启动）
- [ ] T6.1 内网终验 / G3（G1 NO-GO，未启动）

执行关系：`P0 → P1/G1 → P2 → P3 → P4 → P5 → P6`。G1 通过后连续开发；G1 失败则提交官方源码和真实运行证据，不留下半成品生产入口。

本轮执行证据：

- `docs/assessments/2026-07-19-codemap-visualizer-baseline.md`
- `docs/assessments/2026-07-19-codemap-visualizer-selection.md`
