# Skillify `ba3a598` 之后测试环境统一交付说明

> 文档用途：交给独立 Codex/Agent 测试窗口，说明测试环境需要验证的范围和交付证据。
>
> 测试断点：`ba3a5981472d82f7009cc35f6ced0eb33d3c4eba`（含）起，持续覆盖 `main` 后续 Agent 改造；测试窗口必须记录实际检出的 commit SHA。起始提交本身只增加方向文档。
>
> 分支：`main`。状态：代码已完成开发期验证，以下测试环境验收均未销账。
>
> 本文不是测试用例，不规定请求参数、操作脚本或实现方式；测试窗口应根据实际环境执行验证并记录结果。
>
> 统一性声明（2026-07-19）：本文是 `ba3a598` 之后全部未测试改造的唯一测试交付与销账入口。三份专项 E2E 清单的内容已归并到本文，专项文档仅保留为历史来源，不再分别更新状态或勾选。

## 1. 交付边界与判定规则

本次测试覆盖五个连续开发批次：

1. 端侧 Agent 生态：CLI、Provider、能力分发、Workflow Pack、Bridge、Web 任务、业务 MCP、Agent App、扫描与评测。
2. Agent 架构收敛：CodeGraph 替换自研 Code Map、devpi 独立部署、移除自研 Workflow 执行器、在线任务控制面、OpenCode/Claude Code 双执行器闭环。
3. MCP 与委派收敛：官方 MCP SDK、真实 Adapter、Credential Broker、四类身份、工作包确认、执行器原生委派和按任务最小 MCP 注入。
4. Shogun Team Runtime：批准的离线 Shogun 制品、全 OpenCode/全 Claude Code formation、Team 生命周期与并发、控制面事件映射和阶段一运行边界。
5. 人用 Code Map：受个人非商业许可约束的 GitNexus 端侧可视化、只读快照、CLI、Bridge 固定动作、Web 薄入口和本机 Chrome。

测试状态必须分开记录：

- `implemented`：代码已经合入。
- `dev_verified`：离线或替身环境的开发期验证已经通过。
- `env_verified`：本文要求的真实测试环境验证已经通过。

测试窗口只负责判定和记录 `env_verified`。开发期测试通过不能代替测试环境结论；任一阻断项未完成时，不得把对应能力标记为上线可用。

### 1.1 专项清单归并关系

| 原专项清单 | 已归并到 | 当前状态 |
| --- | --- | --- |
| `2026-convergence-e2e-checklist.md` | TP-01、TP-02、TP-03、TP-04、TP-06、TP-11、TP-12 | 全部 `not-run` |
| `2026-mcp-delegation-e2e-checklist.md` | TP-03、TP-05、TP-07、TP-08、TP-09、TP-12 | 全部 `not-run` |
| `2026-shogun-team-e2e-checklist.md` | TP-13 | 全部 `not-run` |

测试窗口只能在本文第 6 节更新最终状态。专项清单中的未勾选项不代表另一套待办，也不得与本文形成两份验收结论。

## 2. 以当前架构为准，不再验证的旧路径

以下能力在后续收敛中已被替换或删除，不属于测试目标：

- 不测试 Skillify 自研 Code Map 的 CLI、MCP、索引和前端视图；测试 CodeGraph 集成及其降级路径。
- 不测试 Skillify 自研的固定角色链或 `execute_workflow`；测试 Workflow Pack 配置、工作包和 OpenCode/Claude Code 原生 Agent 委派。
- 不要求主 Docker Compose 启动 devpi；devpi 是独立服务，主栈只能消费其 index URL。
- 不使用 Web 用户 Token 充当 Endpoint 身份；Endpoint 必须使用独立 device token 或 mTLS 身份。
- 不测试手写 MCP stdio 探测协议；测试官方 MCP Python SDK 的 client/server 往返。
- 不把全部社区 MCP 注入任务；测试按任务声明的最小 MCP 集合以及明确记录的兼容降级。
- 不依赖执行器内部子会话事件判断任务完成；控制面只使用已定义的标准任务事件。

## 3. 测试环境准备

测试窗口开始前应确认以下真实依赖可用，并记录版本、地址类别和部署拓扑；文档和日志中不得写入真实秘密：

- 目标 Linux 主机，包含实际部署架构、glibc 和 systemd user service 条件。
- Skillify Web/API/前端主栈以及可导入初始化 SQL 的真实 DM8。
- Forgejo、真实 Release/Asset、Webhook 和测试仓库。
- Keycloak/RBAC、Endpoint device token 或 mTLS、用户委托身份和服务账号。
- OpenCode、Claude Code、内网模型端点及其锁定版本。
- CodeGraph 离线构件和至少一个具有代表性的中型代码仓库。
- 独立 devpi 及项目锁定的 Python 包镜像；包含 `mcp==1.28.1` 和业务 Skill 依赖。
- 真实 DM8 只读账号、Forgejo、文档检索、CI 和允许访问的内网 REST 服务。
- 供应链工具 Syft、Grype、Cosign；评测/追踪环境 Promptfoo、Phoenix（若本轮部署包含 G8）。
- Shogun 批准离线 bundle、预建 Python 环境、settings 模板，以及目标 Linux 上的 tmux、flock、inotify-tools、Python 和 od。
- 可控制断网、进程退出、凭据过期和服务不可达状态的隔离测试网络。
- GitNexus v1.6.9 固定源码归档、目标 Linux 离线 runtime、Required Notice，以及可执行真实浏览器检查的批准 Chrome。

## 4. 测试包与验收目标

测试窗口应按下列顺序推进。前置测试包未通过时，后续全链路结论保持阻断。

### TP-00 · 既有 SkillHub 核心功能回归

需要验证：

- Keycloak 登录、RBAC、社区首页、分类、搜索、排行榜、Skill 详情和治理信息仍可正常使用。
- Skill 上传、校验、Forgejo Git commit/tag、Release/Asset、Webhook 入库和索引更新链路没有被 Endpoint Agent 改造破坏。
- CLI publish、Web 上传和 Git tag webhook 三个发布入口保持原有职责，重复提交和冲突版本行为明确。
- `skillctl install` 仍能完成下载、checksum 校验、解压、依赖安装和 lockfile 记录。
- Skill 评分、安装统计、精选 Workflow Pack 和真实运行反馈不会覆盖或伪造既有社区数据。
- 单仓库/全量索引重建、Release 中断恢复以及 Forgejo 地址在容器内外不同场景下仍可工作。

该测试包是所有新增 Agent 能力的回归前置；未通过时不得继续给出“改造不影响现有 SkillHub”的结论。

### TP-01 · Linux 部署、DM8 与基础服务

需要验证：

- Linux 上主栈镜像构建、启动、健康检查、前端反向代理和服务重启恢复。
- DM8 初始化脚本可在空库执行，既有业务表以及 Endpoint Task、租约、事件、nonce、工作包结构可用。
- DM8 的 JSON/CLOB、布尔状态、时区、自增、中文、空值和事务行为符合当前模型。
- Endpoint Task 的并发 compare-and-set、lease 续租/过期回收、事件幂等以及工作包确认状态在 DM8 上成立。
- Forgejo 与 Skillify 的 Git、Tag、Release、Asset 和索引职责边界保持正确，数据库之间没有越界依赖。
- 主栈不依赖内置 devpi；devpi 不可用时主服务和不需要 Python 依赖的能力仍可运行。
- DM8、Forgejo PostgreSQL、Forgejo `/data` 和独立 devpi 的备份与恢复流程可执行，恢复后关键任务、发布构件和索引状态一致。

对应门禁：Endpoint G5、Convergence G-P2/G-P4。

### TP-02 · 端侧 CLI、离线构件与双 Provider

需要验证：

- `skillctl agent` 和 `doctor` 在目标 Linux 上正确识别 OpenCode、Claude Code、模型端点、CodeGraph、MCP runtime 和凭据状态。
- OpenCode 离线构件按 manifest 完成安装、校验、升级、降级和损坏包拒绝；不经过公网安装脚本。
- OpenCode 与 Claude Code 均能使用内网模型端点完成真实任务。
- 两个 Provider 的正常结束、用户取消、超时、异常退出、SIGTERM 和清理状态与标准事件一致。
- Provider 只在本机需要的地址上工作，任务停止后没有残留服务、子进程或临时秘密。
- OpenCode session 中断后能够恢复，恢复过程不会重复执行任务。

对应门禁：Endpoint G1、Convergence G-P5。

### TP-03 · 能力分发、权限与独立 devpi

需要验证：

- 一个已发布 Workflow Pack 可从真实 Forgejo 安装、更新、回滚和卸载，checksum、版本、commit 和 lockfile 一致。
- OpenCode 与 Claude Code 能读取 Skillify 生成的各自配置；用户已有配置不被静默覆盖或误删。
- Skill、Workflow、MCP 和任务权限合并后采用最严格边界，端侧能展示并处理需要人工确认的操作。
- 独立 devpi 可通过 index URL 为 Python Skill 和 MCP SDK 提供锁定依赖，断网环境不访问公网。
- MCP 构件安装前能够展示来源、命令、参数、网络、权限和凭据引用；真实内网 MCP 可建立连接。
- Agent self-pull 的首选 `skillctl install` 路径与备用下载/校验路径都能取得精确版本构件并强制校验 checksum；备用路径当前继承 Keycloak 和 Forgejo 可见性，不得误报为已有独立 Agent token 边界。

对应门禁：Endpoint G2、Convergence G-P2、MCP G-M。

### TP-04 · CodeGraph

需要验证：

- CodeGraph 离线构件的来源、版本和哈希正确，可完成安装、升级和回滚。
- 在代表性中型仓库上完成首次索引、增量索引以及删除、重命名后的更新，并记录耗时和资源占用。
- OpenCode 与 Claude Code 均能通过 `codegraph_explore` 定位真实代码证据。
- 关闭遥测后没有公网请求；CodeGraph 不可用或索引失败时，任务可以明确降级到执行器原生检索。
- CodeGraph 失败不会伪造成功证据，也不会阻断不依赖 CodeGraph 的普通任务。

对应门禁：Convergence G-P1。早期 Endpoint G3 已由本测试包替代。

### TP-05 · Workflow Pack、工作包与原生 Agent 委派

需要验证：

- Onboarding、Bugfix、Feature、Review、Refactor 五类 Pack 均能从 Skillify 安装并由真实执行器运行，产物结构符合各 Pack 声明。
- 审批门禁、允许路径、读写权限、验收命令和构件声明在真实任务中生效。
- `suggested` 模式能够生成工作包，用户可以编辑并确认 objective、allowed paths、scope 和并行标志。
- 工作包未确认前 Endpoint 不能领取任务，确认后才能进入租约和执行流程。
- OpenCode 与 Claude Code 的主 Agent 根据确认后的工作包使用各自原生委派能力；控制面不依赖内部子会话事件。
- `adaptive`、`suggested`、`required` 三种委派配置的最终约束符合 Pack 配置，其中 `required` 约束结果而不是强制固定角色链。

对应门禁：Endpoint G4、MCP G-D。

### TP-06 · Web、Bridge、任务控制面与可信事件

需要验证：

- 真实 Keycloak/RBAC 下，用户只能查看和操作自己有权限的 Endpoint 与任务。
- Web 固定 Workflow 表单、执行器选择、工作包编辑/确认、任务确认/取消和结果查看可用，界面不存在任意 prompt 或 shell 下发入口。
- Bridge 仅以出站连接拉取任务、续租、心跳和上报；服务端不需要连接端侧入站端口。
- 重复 pull、重复事件、lease 过期、Endpoint 越权、workspace alias 越权和任务撤销均保持正确状态。
- 网络中断时 Outbox 保存事件，恢复后补传且不丢失、不重复执行、不重复入库。
- Web 时间线只展示真实事件，并正确显示测试摘要、Diff 统计、构件和失败原因，不显示虚构进度。
- 标准事件和构件上报不包含源码、完整 prompt、Token、Cookie、连接串或其他秘密。
- 验证主/子 Agent 数量约束和通讯边界：`delegated` 遵循执行器原生能力；需要明确 Worker 数量和 Team 内通讯时按 TP-13 验证 Shogun，不得把两种模式合并为同一结论。

对应门禁：Endpoint G5、Convergence G-P6/G-P7。

### TP-07 · 官方 MCP SDK 与真实 Adapter

需要验证：

- 从内网 devpi 获取的 `mcp==1.28.1` 与锁文件和离线 manifest 一致。
- 官方 SDK client 能与 `skillctl mcp serve` 启动的真实 stdio server 完成初始化、工具发现、调用和取消。
- `db-readonly` 使用真实 DM8 只读账号，DM8 方言、元数据、SELECT 限制、超时、行数/字节限制和敏感字段脱敏生效。
- Forgejo Adapter 使用最小 scope 读取 Issue/CI；文档 Adapter 只访问允许集合；写操作和写 scope 必须单独授权。
- REST Adapter 只访问 manifest 与本地策略共同允许的 host、port 和 protocol，不接受任意目标地址。
- Adapter 的取消、超时、403、网络不可达和进程崩溃能转换为明确、可审计的任务事件，错误和日志不泄露凭据。

对应门禁：Endpoint G6、MCP G-M/G-A。

### TP-08 · Credential Broker 与身份隔离

需要验证：

- Web 用户、Endpoint 机器、用户委托和服务账号四类身份不能互相替代。
- Web 用户 Token 只用于创建、审批和查看任务；Bridge 使用 device token 或 mTLS 执行拉取、心跳和上报。
- 用户委托身份的 PKCE、Device Flow 或 Token Exchange 能取得目标服务所需 Token；服务账号使用 Client Credentials。
- 目标服务实际校验 Token audience 和 scope，读写能力使用不同的最小权限，写操作保持审批边界。
- Broker 能刷新短期 Token，并在取消、退出、超时后清理任务级临时凭据。
- 真实 keyring/Secret Service 或测试环境选定的本机安全存储可用；降级加密文件满足权限和密钥/密文分离要求。
- CLI、进程参数、MCP 配置、Agent 配置、任务载荷、审计和各服务日志中均不存在明文秘密。

对应门禁：MCP G-C。

### TP-09 · 按任务最小 MCP 注入

需要验证：

- OpenCode 任务只加载已确认工作包声明的 MCP 和工具，不加载其他已安装或社区 MCP。
- Claude Code 的任务级 MCP 配置只包含该任务声明的 MCP 和工具。
- 每个 MCP 的工具摘要、scope 和上下文预算在任务配置中保持有效。
- 执行器不支持 per-task MCP 时，系统明确记录降级，并通过全局安装加任务 allowlist 拒绝未声明工具。
- MCP 凭据只在任务进程需要时注入，不写入 `.mcp.json`、`opencode.json` 或任务产物。

对应门禁：MCP G-D。

### TP-10 · Agent App、本地文件与非技术用户流程

需要验证：

- 本地文档检索 App 只能访问用户选择并映射为 alias 的目录，ignore、大小和敏感目录边界有效。
- CSV/文本批处理使用锁定 Skill 和 devpi 依赖生成新文件、预览及变更清单，不能原地覆盖源文件。
- 非技术用户可以只通过 Web 固定表单下发任务，端侧确认后执行并获得结构化结果和审计记录。
- 需要上传内容或扩大目录范围时存在独立确认，服务端不能枚举端侧文件系统。

对应门禁：Endpoint G7。

### TP-11 · 供应链、评测、社区展示与系统级 hardening

需要验证：

- 真实 Syft、Grype、Cosign 可以生成并校验 SBOM、扫描结果、签名和来源证明，阻断项与警告项分级正确。
- 真实 TaskEvent 能生成成功率、拒绝率、回滚率、测试通过率和阻塞原因；Workflow 新版本回放门禁使用真实数据。
- Promptfoo/Phoenix（如启用）只记录允许的追踪数据，不采集源码、完整 prompt 或秘密。
- Skill/Workflow 详情和精选页面使用真实兼容性、权限、MCP、扫描和运行结果，不把模拟数据展示为真实验收数据。
- 安装、成功、卸载和反馈数据可追溯，默认遥测不包含任务内容。
- 集中执行一次系统级 hardening，并把问题、修复提交、回归范围和剩余风险单独归档。

对应门禁：Endpoint G8、Convergence G-P7。

### TP-12 · 双执行器最终全链路

OpenCode 和 Claude Code 必须分别完成一次真实全链路验收，覆盖：

- Web 下达任务与用户权限检查。
- Endpoint 机器身份拉取、工作包编辑确认和租约建立。
- 执行器原生 Agent 委派及授权 workspace/allowed paths。
- 只加载任务声明的最小 MCP，并通过官方 SDK 调用真实内网服务。
- Credential Broker 获取或刷新目标服务凭据，服务端任务记录不含秘密。
- 标准事件、测试摘要、Diff 统计和构件经断网可恢复链路回传到 Web。
- 正常完成以及拒绝、审批等待、取消、Token 过期、403、网络中断、Adapter/执行器异常等状态均有明确最终结果和审计记录。
- 全过程不发生公网下载、更新或遥测。

对应终验：Convergence G-P7、MCP G-E。两者全部通过后，才能把本轮 Endpoint Agent、MCP 和委派能力标记为 `env_verified=yes`。

### TP-13 · Shogun Team Runtime

需要验证：

环境、许可与离线制品：

- 上游许可为 MIT，批准版本、commit 和制品哈希与 `infra/offline/shogun-manifest.json` 一致。
- 目标 Linux 发行版、CPU、glibc、tmux、flock、inotify-tools、Python 和 od 满足要求。
- 离线 bundle 包含预建 Python 环境、settings 模板和批准入口，不执行 `first_setup.sh`。
- 安装、启动、运行、停止和升级期间无公网下载、更新、通知或遥测；OpenCode、Claude Code 和内网模型端点版本有记录。

两类 formation：

- 全 OpenCode formation 启动 Coordinator、2～3 个 Worker 和独立 Reviewer，并完成真实代码任务、工作包依赖、报告与独立审查。
- OpenCode 的声明式文件权限、互斥 allowed paths、Worker 最小 MCP 和网络策略交集生效，配置中无 dangerous 权限、明文凭据或公网通知。
- 全 Claude Code formation 启动 Coordinator、2～3 个 Worker 和独立 Reviewer，并通过单一共享内网模型端点完成真实代码任务。
- Claude Code 使用受限 `--permission-mode`；allowed paths、最小 MCP、无 push 凭据和默认拒绝网络边界生效，YAML、命令行、上下文和日志无明文凭据。

生命周期、并发与恢复：

- 单 Endpoint 同时只运行一个 Team，额外 Team 排队或明确拒绝；Team 未启用时不影响 `single/delegated`。
- 最大活动 Worker、最大并行模型调用、喂任务节奏和 Team 时长上限生效；429/503 触发退避，空闲 Worker 不产生模型调用。
- 正常完成、取消、超时、Worker 卡死、CLI 崩溃和 Adapter 异常均得到明确最终状态。
- 停止或取消后 supervisor、watcher、tmux session、子进程、临时目录和临时凭据全部清理。
- Bridge 重启后能识别已有 Team，继续上报或安全终止，不重复执行任务。

控制面、事件与审计：

- Web 只在门禁开启后允许选择 Team，并允许选择 preferred CLI、编辑和确认工作包；工作包未确认前 Endpoint 不能领取 Team 任务。
- 全部门禁通过前，`SKILLIFY_SHOGUN_TEAM_ENABLED` 与 `SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED` 保持关闭。
- DM8 保持服务端任务真相源，Shogun 运行目录不能直接覆盖服务端状态。
- Team、Worker、WorkPackage 和 Review 事件稳定映射、顺序合理并按 event ID 幂等；Outbox 在网络恢复后正确补传。
- Web 只展示 Coordinator、Worker、Reviewer 等中立名称和真实时间线。
- 事件、Outbox、YAML、配置和日志不包含 Token、Key、Cookie、连接串、完整环境或原始对话。

阶段一边界与最终启用：

- Worker 可执行 shell 作为上游固有限制，只在受信内网用户本机范围验收。
- 阶段一没有 Worker worktree，依靠互斥 allowed paths，合并只由 Integration 角色执行。
- 同机多 Team、per-Claude 独立端点和混合 formation 不属于阶段一通过条件。
- 失败时只禁用 Team，不恢复 Skillify 自研 Team 通讯或旧 Workflow Runtime。
- 全 OpenCode 和全 Claude Code formation 均通过，License、Offline、Linux、Lifecycle、Security、Events、Workspace、Concurrency、Recovery 门禁全部销账，并完成集中系统级 hardening 后，Team Runtime 才可由负责人批准启用。

对应门禁：Shogun G-S3、G-S4、G-S5、S6、S7。

### TP-14 · 人用 GitNexus Code Map

许可与构件：

- 确认用途保持为个人开发、研究、实验和无预期商业应用；不用于商业推广、收费服务或商业构件分发。
- GitNexus 版本、commit、源码归档 SHA256、LICENSE SHA256 和 Required Notice 与 manifest 一致。
- 在目标 Linux 生成 runtime SHA256 和 SBOM，经内部构件仓分发；Endpoint 运行时不访问 GitHub、npm 或其他公网源。
- 若项目用途变为商业应用，验证该功能默认停用，直到取得适用商业授权或替换引擎。

端侧与浏览器：

- `skillctl codemap visualize doctor/start/status/open/stop` 在批准 Node 22 和 Chrome 上工作。
- 原工作区在扫描前后无变化；`.gitnexus`、registry、HOME、cache 和日志只进入 Skillify 状态目录中的独立快照。
- GitNexus 只监听 `127.0.0.1`，不返回 localhost URL 给中央 Web，不上传源码、索引或查询结果。
- 使用目标 Chrome 验证目录、文件、类、函数、调用/依赖、搜索、过滤和文件行号定位，并确定最低 Chrome major。
- 强制断网后页面核心图谱仍可用；Google Fonts 等外部资源不造成启动失败，浏览器和进程没有公网请求。
- AI Chat、MCP、Shell、Git、Hook、Skill 和改码能力不可从 Skillify 入口获得；集中 hardening 阶段验证上游非展示接口的隔离结果。

控制面与回归：

- Web 的启动、打开、状态、停止固定动作经过既有 Endpoint Task、lease、Bridge、Outbox 和事件表完整往返。
- Codemap Task 自动形成已确认只读工作包，不接收绝对路径、Prompt、Shell 或任意命令参数。
- Bridge 把 Codemap Task 分流到 GitNexus Launcher，不启动 OpenCode、Claude Code 或 Shogun，不注入任何 MCP。
- Bridge 离线、重复拉取、扫描失败、Chrome 缺失、进程退出和 stop 幂等均得到明确事件，恢复后 Outbox 不重复执行任务。
- CodeGraph init/sync/MCP/Agent 查询保持原状；停止、删除或破坏 GitNexus 后，Agent CodeGraph 和既有 SkillHub 功能仍正常。

代码地图评测方案：

评测仓库必须使用真实 Git 仓库，不使用临时生成的假项目代替最终结论。测试窗口开始时为每个仓库记录 official URL、`remote.origin.url`、冻结 commit、默认分支、许可证、文件数和代码语言构成；随后把固定快照镜像到内网，正式断网评测不得临时访问 GitHub。

| 仓库 | 官方 GitHub | 评测定位 |
| --- | --- | --- |
| Skillify | 当前项目 `origin`，以测试窗口实际检出的 `main` commit 为准 | Python + Vue/JavaScript 真实目标仓库；验证本次功能是否满足本项目用户查看需求 |
| Flask | `https://github.com/pallets/flask.git` | 小型 Python 仓库；验证模块、类、函数、装饰器和跨文件调用定位 |
| Element Plus | `https://github.com/element-plus/element-plus.git` | Vue/TypeScript 组件仓库；验证 `.vue`、composable、组件依赖和 TS 调用关系 |
| VS Code | `https://github.com/microsoft/vscode.git` | 大型 TypeScript 压力仓库；验证裁剪、搜索响应、内存上限和浏览器稳定性 |

上述外部仓库只作为评测输入，不进入 Skillify 产品源码、submodule 或发布构件。若测试环境无法取得某个官方仓库，TP-14 状态记为 `blocked`；不得自行换成未知 fork 后继续判定通过。

每个仓库都需要从源码独立抽取一组可复核事实作为 ground truth，不以 GitNexus 自己的输出反向证明自己正确。事实集至少覆盖：

- 目录和文件层级、语言识别以及明确应忽略的构建/依赖目录；
- 类、函数、方法、组件和 composable 的定义文件与起始行；
- 同文件调用、跨文件调用、接口/实现或导入依赖；
- caller → callee 和 callee → caller 两个导航方向；
- Python 装饰器、Vue SFC、TypeScript re-export/alias 等目标仓库中实际存在的结构；
- 至少一个删除或重命名后的重新扫描结果，不能继续导航到旧位置。

ground truth 由源码、语言工具链或人工复核共同形成，并保存相对路径、行号、符号名和关系类型；不得保存源码正文到测试报告。建议每个普通仓库至少抽取 20 个符号定位、20 条调用关系和 10 条模块/组件依赖，大型压力仓库可以使用按模块分层抽样。

质量判定统一记录以下指标：

| 指标 | 通过条件 |
| --- | --- |
| 目标文件覆盖 | ground truth 中非 ignore 文件 100% 可进入目录/文件导航 |
| 符号定位准确率 | 抽样符号中至少 95% 定位到正确相对文件和有效行号 |
| 调用关系准确率 | 抽样 caller/callee 中至少 90% 关系方向与源码一致 |
| 模块/组件依赖准确率 | 抽样依赖中至少 95% 方向与目标一致 |
| 搜索可达性 | ground truth 符号至少 95% 能通过名称搜索或图导航到达 |
| 失效引用 | 删除/重命名并重新扫描后不得保留已确认的旧路径或旧符号 |
| 重复扫描稳定性 | 同 commit、同配置连续两次扫描的文件/符号/边计数一致；如上游存在非确定布局，只允许视觉坐标变化 |

发现误报和漏报时必须记录关系类型、语言、相对路径、期望与实际结果；不得只给出“图看起来正确”的主观结论。Skillify、Flask、Element Plus 任一质量硬项不达标，TP-14 记为 `failed`。VS Code 只承担大型仓库性能与稳定性门槛，不以其全部图关系进行穷举正确性判定。

性能评测按仓库实际生成的 node 数分档，不按仓库名称预设规模。冷启动和重复启动分开记录，至少记录扫描时间、索引大小、服务就绪时间、Chrome 首次可交互时间、搜索/过滤 P50/P95、峰值 RSS、CPU 峰值、文件/符号/边数量和硬件信息：

| 实际规模 | 首次可交互 | 搜索/过滤 P95 | 峰值内存 |
| --- | ---: | ---: | ---: |
| ≤10k nodes | ≤5s | ≤1s | ≤1.5 GiB |
| ≤50k nodes | ≤15s | ≤2s | ≤3 GiB |
| ≤100k nodes | ≤30s | ≤3s | ≤4 GiB |

“首次可交互”从 GitNexus 服务报告 ready 后开始计时，不把此前源码扫描时间隐藏在该指标中；扫描时间必须作为独立数据报告。超过 100k nodes 时允许按模块/深度裁剪，但必须出现明确提示，不能让 Chrome 无提示卡死。任何规模发生进程崩溃、页面失去响应、索引损坏或停止后残留进程，性能/稳定性判定失败。

TP-14 最终证据应包含一张仓库结果矩阵，逐仓库列出冻结 commit、规模、质量指标、性能指标、Chrome major、网络观察、工作区前后状态和结论。总状态只允许 `passed`、`failed`、`blocked` 或 `not-run`：许可、离线构件、质量、只读隔离、localhost、浏览器、控制面、CodeGraph 回归和性能门槛全部通过后，才能把 Code Map 标记为 `env_verified=yes`。

对应门禁：Code Map G2、G3。当前全部 `not-run`。

## 5. 测试交付证据

测试窗口不需要在本文编写测试用例，但每个测试包必须提交以下结果：

- 测试环境清单：系统、架构、服务和关键构件版本，以及使用的 commit SHA。
- 测试包结论：`passed`、`failed`、`blocked` 或 `not-run`，不得用“基本通过”。
- 真实关联标识：任务 ID、Endpoint ID、事件 ID、工作包 ID 和构件 ID；不得记录凭据。
- 脱敏日志或审计导出，能够证明状态变化、权限拒绝、降级和故障恢复。
- 网络与进程边界证据：无公网访问、仅预期本机监听、任务停止无残留进程。
- 数据层证据：DM8 迁移版本、关键状态和幂等/租约结论，不导出业务敏感数据。
- 失败或阻断记录：所属测试包、环境、复现条件、影响范围、负责人和复验条件。

发现代码缺陷时，测试窗口先记录证据和阻断 Gate；不要在没有单独开发授权的情况下顺手改造架构或扩大 hardening 范围。

## 6. 最终销账表

| 测试包 | 状态 | 主要 Gate |
| --- | --- | --- |
| TP-00 SkillHub 核心回归 | blocked | 全部新增能力前置 |
| TP-01 Linux/DM8/基础服务 | blocked | G5、G-P2、G-P4 |
| TP-02 CLI/离线构件/双 Provider | blocked | G1、G-P5 |
| TP-03 能力分发/权限/devpi | blocked | G2、G-P2、G-M |
| TP-04 CodeGraph | passed | — |
| TP-05 Workflow/工作包/原生委派 | blocked | G4、G-D |
| TP-06 Web/Bridge/控制面 | blocked | G5、G-P6、G-P7 |
| TP-07 官方 MCP SDK/Adapter | blocked | G6、G-M、G-A |
| TP-08 Credential Broker/身份 | passed | — |
| TP-09 按任务 MCP 注入 | blocked | G-D |
| TP-10 Agent App | blocked | G7 |
| TP-11 供应链/评测/hardening | blocked | G8、G-P7 |
| TP-12 双执行器最终 E2E | blocked | G-P7、G-E |
| TP-13 Shogun Team Runtime | blocked | G-S3、G-S4、G-S5、S6、S7 |
| TP-14 GitNexus Code Map | blocked | Code Map G2、G3 |

只有 TP-00 至 TP-14 全部通过，或非适用项有明确的产品裁决和证据，才可完成本轮测试环境交付。

### 6.1 2026-07-20 第一轮测试记录

测试断点与拓扑：

- 当前项目 commit：`e1761ec43fa4b959c7cb09f0a616ce097b4c8282`，`main`，测试开始时工作树干净。
- 当前项目按测试负责人要求仅在 Windows 11 本机 `E:\skillify` 与仓库 `.venv` 运行；当前项目尚未迁移到服务端。
- 服务端外部依赖位于 `192.168.124.2`：DM8 `5236`、Forgejo `3000`、独立 devpi `3141`、Keycloak `18085`、RBAC `5005`；本机与端侧虚拟机对上述 HTTP 依赖的健康/发现入口均实测返回 `200`。
- 端侧为银河麒麟 V10 SP1，OpenCode `1.17.18`、Claude Code `2.1.179`、Chrome `145.0.7632.159`。端侧现装 `skillctl 0.1.0` 的 `doctor` 全绿，但不含 `agent` 命令，因此不得作为当前 commit 的 TP-02 验收构件。

TP-00 结论：`failed`。

- 本机后端使用 `.venv`（Python `3.13.0`、pytest `9.1.1`）执行 `pytest -q --continue-on-collection-errors`：`249 passed, 6 skipped, 10 failed, 51 errors`。
- 收集错误及失败主要由当前源码直接依赖 Linux/POSIX 能力引起，包括 `fcntl`、`os.killpg`、`os.getpgid`、Unix domain socket、POSIX 权限位、shell 可执行文件与 Windows 符号链接权限。
- `import skillify.web.app` 在本机稳定失败于 `src/skillify/agent/capability_lock.py` 的 `import fcntl`，所以当前后端不能按指定的 Windows `.venv` 拓扑启动。
- 前端 Vitest 为 `172 passed, 1 failed`；失败项为 `web/tests/appFooter.spec.js` 的授权快捷入口断言。`web/src/layouts/AppFooter.vue` 中对应渲染块被注释并固定显示“暂无可用入口”，属于可稳定复现的代码/测试不一致。
- 前端 `vue-tsc --noEmit` 与 Vite production build 通过。Vite `4.5.14` 在本机 Node `24.9.0` 下监听 `0.0.0.0:5173`；浏览器使用 `Accept: text/html` 访问 `http://192.168.124.5:5173/` 与 `/index.html` 均返回 `200`。早期无 HTML Accept 的 PowerShell 根路径探测返回 `404`，不作为浏览器入口故障。
- Playwright `1.61.1` + 本机 Chrome 经 `http://192.168.124.5:5173/` 完成 Keycloak 登录并返回 Skillify；Keycloak 密码授权成功，远程与 Vite 代理的 Skillify `/api/skills`、RBAC `/api/auth/login`、`/api/admin/index` 均返回 HTTP `200`，RBAC 业务码为 `0`。社区首页、排行榜、个人空间、上传入口及五个 RBAC 管理页面只读巡检无 4xx/5xx、请求失败或控制台错误。
- 服务端现有 API 版本早于当前前端：其 OpenAPI 只有 29 条旧社区路径，`/api/categories`、`/api/endpoints`、`/api/endpoint-tasks` 均为 `404`。技能详情响应缺少当前前端要求的 `governance` 字段，`SkillGovernancePanel` 读取 `governance.scanStatus` 抛出 `TypeError`，导致安装、治理、文档、版本、评论与侧栏 DOM 全部未渲染。该旧后端不得作为当前 commit 的完整 TP-00 验收后端。
- RBAC Swagger UI 返回 `200`，且 RBAC 业务接口可用；其配置的 `swagger/v1/swagger.json` 返回 `500`，单独记录为文档端点故障。
- 复验条件：明确当前后端是否要求支持 Windows；若要求，修复 POSIX 导入/进程/锁/Unix socket 的跨平台边界并重跑全量 pytest；同时修复或裁决 Footer 快捷入口契约，并在受支持 Node 版本重跑 Vitest、type-check、build 与本机页面访问。

TP-01 结论：`blocked`。

- `E:\DM\bin\DIsql.exe` 存在（`disql V8`），本机到 `192.168.124.2:5236` 的 TCP 连接成功；测试提供的 SYSDBA 身份可完成只读登录，未在文档或日志中记录凭据。
- 复用服务端现有应用连接进行只读查询，确认方言为 `dm`、数据库为 `DM Database Server 64 V8`、schema 为 `SKILLIFY_TEST`，`CURRENT_TIMESTAMP` 查询成功。
- DM8 `COMPATIBLE_MODE=0`、`ENABLE_ENCRYPT=0`；当前八张表共有 13 个已启用主键/唯一约束。
- 当前 schema 只有 `skill_comments`、`skill_events`、`skill_index`、`skill_namespace_owners`、`skill_publish_jobs`、`skill_ratings`、`skill_stars`、`skill_subscriptions` 八张表；尚未应用 `06-endpoint-tasks.sql`、`07-endpoint-task-runtime-lease.sql`、`08-work-packages.sql`、`09-team-tasks.sql`。
- 当前业务账号可查询 `USER_TAB_COLUMNS`，但 SQLAlchemy/dmSQLAlchemy 列反射访问 `SYS.SYSCOLUMNS` 时被 DM8 以 `-5504 No select privilege` 拒绝。该现象需判断为方言反射权限缺陷还是预期的最小权限边界，不得直接通过扩大系统表权限规避。
- `SKILLIFY_SHOGUN_TEAM_ENABLED` 与 `SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED` 均未设置，符合全部 Team Gate 销账前保持关闭的要求。
- 复验条件：先备份并审核 06～09 增量 SQL 的顺序、非幂等 DDL 与回滚方案，经测试负责人授权后导入，再核对表/列/约束并执行 DM8 类型往返、并发 CAS、lease、事件幂等和工作包确认测试。

### 6.2 2026-07-20 第二轮 Linux 迁移与真实环境测试记录

部署与自动化门禁：

- 测试负责人裁决当前项目只支持后续 Linux 部署，不再把 Windows/POSIX 导入差异作为兼容目标。本地修改后通过安全文件传输同步至 `root` Linux 测试服务器；候选目录先独立构建和测试，现网切换前未修改原实例。
- 当前源码在 Linux Python 3.12 容器中全量 pytest 为 `984 passed, 8 skipped, 0 failed`。修复了 root 容器读取无权限 Agent 日志时未失败关闭的问题，并把离线 skillctl approval 占位文件的实际 SHA256 同步到 manifest；两条原失败用例和全量测试均复验通过。
- 本地前端为 `20 files / 173 tests` 全绿，`vue-tsc --noEmit` 与 production build 通过；修复 Footer 授权快捷入口被注释的问题。Compose 配置测试 `6 passed`，Footer 定向测试 `2 passed`。
- 当前版本已部署到 `/opt/skillify-test/app`，旧版本保留在 `/opt/skillify-test/backups/app-20260720-100620`。`skillify-web`、`frontend` 健康，webhook 运行；`/healthz` 为 `200`，OpenAPI 为 38 条路径并包含 `/api/endpoint-tasks`。
- 服务器前端迁移后首次暴露两个真实配置问题：Keycloak 缺少 `http://192.168.124.2:18090/*` 回调，RBAC 未向该 Origin 提供 CORS。已用测试账号的 `manage-clients` 权限只追加 Keycloak redirect URI/Web Origin；RBAC 通过本项目 Nginx `/rbac-api/` 同源代理解决，未修改或注入 RBAC 服务凭据。

TP-00 当前结论：`blocked`。

- 真实 Keycloak 令牌下，健康、社区列表、搜索、排行榜、个人空间、Endpoint 与 Task 查询均返回预期状态；未认证和非法 token 均为 `401`。Skill 详情响应包含完整 `governance`，旧版 `governance.scanStatus` 空值崩溃已消失。
- 本机 Chrome 直接访问服务器 `18090` 完成 Keycloak/RBAC 登录；主页出现 9 个授权 Footer 快捷入口和 6 个 Skill 链接，详情页存在安装区域和治理面板，全程无 4xx/5xx、控制台错误或失败请求。
- 真实 Web guided/native/external 发布烟测 `26/26` 通过，覆盖用户隔离、路径穿越拒绝、陈旧 revision、未确认发布、重复版本冲突、多候选导入与搜索回读。临时隔离用户已删除。
- 本轮三个 Forgejo 仓库均存在 `v1.0.0` tag；每个 Release 有 4 个 Asset，三份 tarball 的 SHA256 均与 Release 校验文件一致。
- 端侧从真实 Release 完成 `skillctl install`、checksum 校验、OpenCode 投影、lockfile 写入和 `remove` 清理。CLI `skillctl publish` 因端侧 Forgejo token 缺少建仓/写 scope 返回 `403`；按身份隔离要求未使用服务器服务账号 token 绕过。Git tag webhook 入口、全量索引重建和发布中断恢复尚未完成，因此 TP-00 不得标记通过。

TP-01 当前结论：`blocked`。

- 已按 06、07、08、09 顺序直接迁移 `SKILLIFY_TEST`。新增 7 张 `ENDPOINT_*` 表，核验为 10 个约束、23 个索引；`ENDPOINT_TASKS`、`ENDPOINT_TASK_EVENTS`、`ENDPOINT_WORK_PACKAGES` 分别为 24、13、15 列。
- 应用账号真实往返验证中文 CLOB/JSON、BIT、NULL、时区时间、自增 ID、事件 ID 唯一约束、CAS 首次/陈旧更新 `1/0`、lease/heartbeat 更新和事务 rollback，全部通过；唯一临时记录已反向清理。
- devpi 已由 `infra/devpi/docker-compose.yml` 独立接管并复用原 `skillify_devpi-data` 数据卷。停止 devpi 期间主站健康和 OpenAPI 仍为 `200`，恢复后 `+status=200`；应用三容器重启后恢复健康。
- 银河麒麟端侧可跨机访问主站、前端、Keycloak、Forgejo 和 devpi；RBAC 未带认证为 `403`，属于预期保护，不需要开启虚拟机桥接。
- DM8、Forgejo PostgreSQL、Forgejo `/data` 与 devpi 数据卷的实际备份恢复演练尚未执行，因此 TP-01 保持阻断。

TP-02/TP-03/TP-07 与后续阻断：

- 当前 wheel 在端侧隔离 Python 3.13 环境安装；端侧系统 Python 3.8 不满足项目 `Python >=3.10`，未降低项目要求。49 个锁定 wheel 的临时离线 wheelhouse 安装成功；兼容 glibc 2.17/2.31 的 cryptography manylinux2014 wheel SHA256 与 `uv.lock` 一致。
- OpenCode `1.15.11` 官方制品按 manifest SHA256 校验后隔离安装，未覆盖端侧现有 `1.17.18`。Agent doctor 的平台、OpenCode、Git、cache、workspace、离线 manifest、版本与 checksum 必需项通过；模型与 Provider 真实任务结果见 6.3。Claude Code 为 `2.1.179`。
- 独立 devpi 的历史缺包与上传身份问题已在 6.3 解决，TP-03 从 `failed` 调整为 `blocked`；Workflow Pack 更新/回滚、最严格权限合并与真实远程 MCP 连接仍未完成，不能标记通过。
- 官方 MCP SDK 的本机 stdio 往返通过：注册表列出 `db-readonly`、`documents`、`echo`、`forgejo`，echo 完成工具发现和调用。远程 HTTPS MCP、真实 DM8 只读账号、Forgejo 最小 scope Adapter 与文档 Adapter 未提供专用凭据/端点，TP-07 保持阻断。
- CodeGraph 未在端侧 PATH，Shogun offline bundle 未配置，GitNexus runtime/评测仓库未部署；Endpoint device token/mTLS、用户委托身份、服务账号和远程 MCP 凭据也未交付。因此 TP-04～TP-14 的相关真实任务不得继续伪测或标记通过，Team 开关继续保持关闭。

### 6.3 2026-07-20 第三轮：devpi、Forgejo、DeepSeek 与 RBAC 补充验证

- devpi 历史上传凭据无法恢复，已重置管理入口并创建专用 `skillify-uploader`，仅加入 `skillify/dev` 的上传 ACL。锁定 wheelhouse 共 49 个 wheel 已上传，包含此前缺失的 `dmpython==2.5.32`、`dmsqlalchemy==2.0.12` 与 `mcp==1.28.1`。端侧全新 Python 3.13 venv 仅使用 devpi 索引安装 `skillify==0.1.0`，核心依赖导入通过；测试环境 HTTP 索引需要显式 trusted-host，生产不得沿用该豁免。
- Forgejo 为现有 `skillify-bot` 签发了端侧专用 Token，scope 限定为 `write:repository,write:organization`，Token 只写入端侧隔离配置。真实 `skillctl publish` 成功创建 `skillify/e2e-cli-1784516943` 并发布 `v0.1.0` Release；未在仓库、文档或日志中记录 Token。
- DeepSeek 的 OpenAI 兼容入口与 Anthropic 兼容入口均完成真实请求并返回 HTTP 200。OpenCode 受管任务首次暴露 SSE 适配缺陷：普通文本 `message.part.updated` 被误按工具事件校验并失败；修复后 Linux 定向回归为 `43 passed`，重建 wheel 经 devpi 覆盖安装，受管任务返回 `state=succeeded`。Claude Code `2.1.179` 通过 `/anthropic` 入口完成真实生成并返回指定结果。API Key 仅从任务进程标准输入注入，未落盘。
- 本地保存两份不含 Key 的测试 profile：`infra/test-env/deepseek-opencode.yaml` 与 `infra/test-env/deepseek-claude-code.yaml`。模型名、base URL、允许主机和凭据环境变量名均已固化，实际 Key 继续由运行时注入。
- RBAC 审计覆盖全部 11 个非登录/错误 Vue 视图：10 个可见页面与 1 个 `add_rules_only` Skill 详情动态路由。新增 `Endpoint Tasks` 规则后，`/api/rule/tree` 与超管 `/api/admin/index` 均返回该路由；规则已补入幂等初始化 SQL。Playwright 使用真实 Keycloak/RBAC 登录逐页访问 10 个可见页面，全部 HTTP 200，实际路由一致，控制台错误、页面异常及 4xx/5xx 请求均为 0。
- 当前轮次不再需要额外模型参数。继续推进 TP-04～TP-14 前仍需测试负责人评估或提供：Endpoint device token/mTLS 的签发方案、远程 MCP 专用凭据与端点、DM8 只读 MCP 账号、Shogun 离线授权构件、CodeGraph/GitNexus 运行构件与评测仓库，以及数据卷备份恢复演练窗口。

### 6.4 2026-07-20 第四轮：Endpoint 身份、DM8 MCP、CodeGraph、GitNexus 与恢复演练

本轮授权与安全边界：

- 测试负责人批准一机一 Endpoint device token、DM8 MCP 只读账号、四类身份模型、Shogun/CodeGraph/GitNexus 离线构件，以及只恢复到临时实例的恢复演练。所有生成的 Token、客户端 Secret 和数据库密码只保存在端侧或服务器的 `0600` 凭据文件中，本文不记录值。
- 四类身份完成真实边界验证：Web 用户访问 Web API 为 `200`、访问 Endpoint pull 为 `401`；Endpoint device token 访问 pull 为 `200`、访问 Web API 为 `401`；PKCE 用户委托 Token 与 Client Credentials 服务账号 Token 访问 Web API和 pull 均为 `401`。委托 Token 与服务 Token 的有效期均为 300 秒，PKCE refresh token 在测试后通过 logout 返回 `204` 并清理。
- Keycloak 创建 `skillify-user-delegation-test` 公共 PKCE 客户端与 `skillify-automation-test` 机密服务客户端；前者关闭 Direct Grant/Service Account，后者关闭浏览器登录/Direct Grant。服务账号凭据仅保存在服务器 `/opt/skillify-test/credentials/keycloak-automation.env`，权限为 `0600`。

TP-04 CodeGraph 结论：`passed`。

- 官方 CodeGraph `v0.9.6` x86_64 归档 SHA256 为 `7c2f…a02e`，端侧在 `CODEGRAPH_NO_DOWNLOAD=1`、关闭遥测和无公网依赖条件下安装运行。完整索引为 345 个文件、5,706 个节点，数据库约 10.58 MiB；状态为 up to date。
- 真实 MCP 调用和 CLI 查询均可定位 `src/skillify/tasks/lease.py:28` 的 `claim_next_task`。发现上游 `v0.9.6` MCP 不读取 `CODEGRAPH_PROJECT_ROOT`，已在 OpenCode/Claude Code 配置中补充显式 `--path`，Linux 定向测试 `6 passed`。
- 停止 GitNexus 后，CodeGraph `status/query` 仍返回 `rc=0`；Skillify `/healthz` 保持 `200`。GitNexus 恢复后服务器和端侧转发均重新返回 `200`，证明两套 Code Map 不互相兜底或耦合。

TP-07 DM8 MCP 补充结论：`blocked`。

- 创建专用 `SKILLIFY_MCP_RO` 登录账号和 8 个脱敏只读视图，只覆盖 Skill、Endpoint、Task/Team/Work Package 所需字段。账号只拥有这些视图的 SELECT；读取业务基表和执行 DELETE 均被 DM8 拒绝。
- 官方 MCP stdio 工具发现只列出 8 个安全视图，计数查询成功，原始表查询和写操作均以工具错误拒绝。端侧 DM8 驱动要求在进程启动前设置其私有 OpenSSL 库路径，已固定在隔离 MCP 环境中。
- 远程 HTTPS MCP、Forgejo 最小 scope MCP Adapter 与文档 Adapter 仍未完成，因此 TP-07 不能仅凭 DM8 stdio 通过。

TP-08 Credential Broker 与身份结论：`passed`。

- Web user、Endpoint、user-delegated、service-account 四种身份均完成真实签发/验证及交叉负测；不能互相替代。DM8 MCP、devpi uploader、Forgejo publisher 与 GitNexus tunnel 分别使用独立最小权限服务身份。
- DM8 MCP 账号写入和原表读取被拒绝；devpi uploader 只在 `skillify/dev` ACL；Forgejo 端侧 Token 只含批准的 repository/organization 写 scope；GitNexus tunnel 用户为锁定 shell，authorized key 仅允许转发到 `172.24.0.2:4747`。
- API Key 仍只经进程标准输入注入；令牌、Secret、MCP 配置和测试文档均未记录明文秘密。

TP-13 Shogun Team Runtime 结论：`blocked`，Team 开关继续关闭。

- 官方 `v5.2.0`/commit `431b86a…` 构件 SHA256 为 `04bc…afbe`；端侧已离线补齐 tmux `3.0a`、flock、inotifywait、Python 和 od，从未执行会联网和改用户配置的 `first_setup.sh`。
- 上游运行时仍硬编码安装根目录下的 settings/queue，未采用 Skillify 的隔离路径；starter 创建 tmux 后退出，而 Provider 跟踪的是 starter PID；当前还没有把短期模型凭据安全注入每个 pane 的 broker。直接启动会造成生命周期误判或迫使凭据落盘，因此 manifest 保持 `installable=false`，不得启动真实 Team。

TP-13 Shogun Team Runtime 第五轮补充：代码解阻断（2026-07-20）。

TP-13 的三个代码阻断项已完成适配层修正并达到 `dev_verified`，上游源码保持未修改：

- 完成 commit `431b86a…` 六问源码取证，证据见 `docs/2026-07-20-shogun-431b86a-source-findings.md`。结论均可通过上游公开目录布局、tmux 行为和 CLI 可执行解析在 Skillify 适配层解决，不触发 `upstream-contribution-or-blocker`。
- 每任务把批准 bundle 以硬链接/原样符号链接投影到隔离运行目录；可变的 `config`、`queue`、`logs`、`dashboard.md` 不共享。入口、Provider 写入和事件扫描统一使用该任务目录，并设置任务专属 `HOME` 隔离 Linux inbox。
- 生命周期改用可持久化 `TeamHandle(session, run_dir)`。存活判断跟随 tmux session，不再跟随启动后退出的 starter PID；停止/取消按运行目录脚本路径先停 supervisor/watcher，再关闭固定 session，并保留单 Endpoint 单活约束。
- 新增 pane 凭据注入器：只把 `credential_ref` 写入 settings；短期令牌经既有 `CredentialBroker` 获取，并通过任务专属、权限 `0600`、校验同 UID/运行目录/pane 标识的 Unix Socket 交给固定 CLI launcher。starter 仅继承显式非秘密环境白名单，令牌不进入 YAML、命令行、事件、日志或共享父环境。
- Bridge/TaskRunner 持久化并恢复 Team handle、Provider handle 和 session。重启后 session 存活则复用原 session 和 queue 继续幂等上报；已死亡、状态损坏或只有残留 guard 的 Team 安全清理并报告 `team-recovery-dead`，不重复执行。
- 本机专项用例为 `10 passed, 2 skipped`（跳过 Linux-only Unix Socket/Provider）；服务器独立副本 `/opt/skillify-test/tp13-dev-20260720` 的 Linux 专项为 `13 passed`，全量回归为 `996 passed, 8 skipped`。批准归档 SHA256 复核为 `04bc…afbe`，真实归档双任务投影确认 queue、入口和 HOME 相互隔离且入口与上游文件为同 inode。

TP-13 当前仍为 `blocked`，只剩真实环境门禁，不是上述三个代码根因未修复：

- 服务器 `192.168.124.2:2223` 当前缺少 `tmux` 和 `inotifywait`；批准源码归档不含 manifest 要求的预建 `.venv/bin/python`，尚不是可安装离线 bundle。
- 测试环境尚未向 Bridge 提供可签发短期模型凭据的 Credential Broker profile/ref/scope 接线；代码会在 credential ref 与批准环境变量名不一一对应时 fail closed，不会退回共享 API Key 环境。
- 全 OpenCode、全 Claude Code 的真实 formation、取消/崩溃/重启恢复、无秘密审计和无残留检查尚未执行。

因此 `infra/offline/shogun-manifest.json` 继续保持 `installable=false`，`SKILLIFY_SHOGUN_TEAM_ENABLED` 与 `SKILLIFY_AGENT_SHOGUN_TEAM_ENABLED` 继续关闭。不得以本轮 FakeRuntime/容器测试替代 `env_verified`。

TP-13 Shogun Team Runtime 第六轮补充：真实批准构建测试（2026-07-20）。

本轮在 Endpoint `192.168.124.2:2222` 的银河麒麟 V10 SP1 上建立候选离线 runtime；服务端 CentOS 7 因 glibc 2.17、Python 3.6 且缺少 tmux/inotifywait，不作为 CLI 执行宿主。真实结果如下：

- 启动与生命周期门禁通过：适配 tmux 3.0a 不支持的 `window-size latest`，补齐非交互 `TERM/LANG/PATH`，并把 readiness 覆盖上游自身最长 30 秒探测周期。OpenCode 与 Claude Code 均实际启动四类角色、两个 tmux session 和 10 个 pane；starter 正常退出后 Team 仍存活。首次残留复核发现 Claude 退出阶段会在 session 关闭后短暂重写隔离 HOME，现已按 `/proc/*/cwd` 精确终止仍位于 Team 运行目录的子进程，等待退出后再清理；4 秒延迟复核确认 session、guard、运行目录及临时凭据 socket 均无残留。
- 凭据门禁通过：两个 formation 均由测试 broker 通过 `0600` Unix Socket 向 pane launcher 临时注入模型凭据。审计未在运行目录文件或 `/proc/*/cmdline` 发现明文，broker 在停止时清空；测试脚本只从 stdin 接收凭据。
- 同步最终生命周期修正后，Endpoint 在显式加入 `~/.local/bin` 的正式非登录 PATH 下完成 Linux 全量回归：`1001 passed, 8 skipped`。未加入该 PATH 的首轮失败仅为 `uv` 不可发现导致，不作为代码结果。
- 候选 runtime 归档位于端点 `/home/fzq/.skillify-test/tp13-approved-20260720/artifacts/multi-agent-shogun-431b86a-kylin-x86_64-runtime.tar.gz`，大小 `55,110,691` bytes，SHA-256 为 `add4076b3af18ce7c5c7a5c6e40211740ae0eab2ba54782ee05334e6b22921c8`；包含安全 settings 占位与预建 PyYAML 6.0.3 `.venv`。该文件是 NO-GO 复现候选，不代表批准启用。
- OpenCode 启动阻断已修正：原配置漏掉 `cli.agents.shogun`，导致主将错误回退 Claude；补齐后四个角色均为 OpenCode。关闭自动更新提示后，启动门禁通过。真实任务可以触发模型和上游消息流程，但两次 180～240 秒闭环均未稳定产生规范的 `task.status=done`、独立审查和最终验收组合，因此“全 OpenCode formation 完成任务”未通过。
- Claude Code 启动阻断已修正：隔离 HOME 只预置非敏感 onboarding/theme/project-trust 状态并关闭自动更新；四个角色均进入 Claude CLI。真实任务在首个上游自识别 `tmux display-message` Bash 调用处等待人工权限确认。未使用 `--dangerously-skip-permissions`，所以“全 Claude formation 完成任务”未通过。
- 发现完整批准级额外阻断：上游 `build_instructions.sh` 将全部 `ashigaruN` 固定映射为同一 `ashigaru` 权限角色，只消费 `read_allow/read_deny/edit_allow/edit_deny`；当前逐 Worker WorkPackage 权限无法由该公开格式表达。同时 Provider 尚未把业务 `workspace` 映射为可受控的运行时工作树，上游又没有 per-Worker worktree。Workspace、Security、OpenCode、Claude Code 四项 Go/No-Go 门禁均未通过。

结论：TP-13 三个原始根因的真实启动、生命周期和无秘密注入已得到环境证据，但本次批准构建结论仍为 `NO-GO / blocked`。manifest 与两个 Team feature flag 保持关闭，未翻转任何生产批准状态，也未修改上游源码。

TP-14 GitNexus Code Map 结论：`blocked`。

- 固定 GitNexus `v1.6.9`/commit `4227194…`，源码 SHA256 `468138…77c90`、LICENSE SHA256 `b3e617…15c72`。Node `22.23.1` 官方归档哈希核验通过；银河麒麟原生运行因 glibc/OpenSSL ABI 不满足而未替换系统 glibc，改在服务端 Debian 容器运行。
- runtime 镜像 `skillify/gitnexus-test:1.6.9` 以非 root `node` 用户运行，无宿主端口，连接显式 internal Docker 网络。镜像离线归档 SHA256 为 `13cba525…c8ba9`（382,330,908 bytes），CycloneDX SBOM SHA256 为 `a7b823f4…fe3d0`。
- 端侧仅通过锁定服务账号和 `permitopen=172.24.0.2:4747` 的 SSH key 暴露 `127.0.0.1:4747`；端侧 curl 为 `200`。服务端容器无公网网络，构建产物已移除 Google Fonts 标签。首次构建/每个新索引准备阶段曾临时联网安装 Ladybug FTS 扩展，正式运行网络为 internal；后续离线包必须携带已准备的扩展/索引。
- 独立快照索引结果：skillify 7,956 nodes/18,941 edges/84.9 秒，Flask `3.1.3` 2,142/3,423/15.4 秒，Element Plus `2.14.0` 14,618/25,775/15.8 秒。官方评测源码归档 SHA256 分别为 Flask `36a618…88477`、Element Plus `6b6b3a…c0cfd`。
- 源码独立抽样的符号路径/定位复核：skillify `20/20`、Flask `20/20`、Element Plus 非忽略文件 `19/19`。GitNexus 内部不同解析器的 `startLine` 存在 0/1 基混用，同文件同名方法会返回多条，需作为上游缺陷保留；位置仍能落在实际定义/装饰器行。Element Plus 的 `__tests__` 被上游默认忽略，不计入非 ignore 覆盖。
- 目标 Chrome `145.0.7632.159` 的 headless 网络进程对端侧 loopback 仅发出导航请求但始终不收到响应；同一 `4747` 后端和本地静态 `4748` 用 curl 均为 `200`。因此真实目录/图谱交互、搜索 P95、首次可交互、浏览器公网请求和 Chrome 最低版本门禁未通过；控制面 `codemap visualize` 全链路与调用/依赖 20/20 质量抽样也尚未完成，TP-14 不得标记通过或设置 `env_verified=yes`。

TP-01 恢复演练补充结论：`blocked`。

- Forgejo PostgreSQL custom dump、Forgejo `/data` 和 devpi 数据卷完成在线备份，并恢复到独立 internal 网络、临时容器和临时卷。Forgejo 原/恢复实例的 repository、release、attachment 计数均为 `10/10/34`，恢复站点为 `200`；devpi `+status` 和 `skillify/dev/+simple/skillify/` 均为 `200`。
- 备份保存在服务器 `/opt/skillify-test/recovery-drill/20260720-restore-drill`：Forgejo DB、Forgejo data、devpi data 的 SHA256 分别为 `857f8c…ee6c`、`f06e13…4839`、`e3d442…9e18`。验证后临时容器、网络和卷全部删除，当前实例未停止或恢复覆盖。
- DM8 使用本机官方 `dexp V8` 成功导出 `SKILLIFY_TEST` 的 15 张表和 8 个 MCP 视图，导出文件位于 `E:\skillify-artifacts\recovery-drill\20260720-dm8\skillify-test.dmp`，SHA256 为 `f201aae9…cccb`。服务器没有 DM8 镜像、安装介质或第二实例，无法遵守“只恢复到临时实例”前提完成导入复验，因此 TP-01 仍被 DM8 临时恢复构件阻断。

## 7. 来源文档

以下文档只作为需求与历史清单来源；测试状态统一在本文第 6 节维护：

- `docs/2026-07-16-endpoint-agent-tasks.md`
- `docs/2026-07-16-skillify-agent-architecture-convergence-task.md`
- `docs/2026-07-16-skillify-endpoint-mcp-and-agent-delegation-task.md`
- `docs/testing/2026-convergence-e2e-checklist.md`
- `docs/testing/2026-mcp-delegation-e2e-checklist.md`
- `docs/development-delivery-dm8-readiness-c3-2026-07-11.md`
- `docs/agent-self-pull.md`
- `docs/2026-07-18-skillify-shogun-team-runtime-task.md`
- `docs/testing/2026-shogun-team-e2e-checklist.md`
- `docs/2026-07-19-skillify-codemap-visualization-task.md`
- `docs/testing/2026-codemap-visualizer-dev-verification.md`
