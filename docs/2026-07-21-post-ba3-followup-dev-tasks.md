# Skillify `ba3a598` 之后后续开发任务书（交付 Codex/GPT）

> 用途：交给独立 Codex/GPT 开发窗口，作为 `ba3a598` 测试交付说明之后的**开发**任务书。区别于 `docs/testing/2026-07-17-post-ba3-test-environment-handoff.md`（那是测试销账入口），本文只定义**需要开发或收口的代码工作**与**必须由真机验证的前置门禁**。
>
> 生成依据：`main`（审计时 `06af983`）**源码审计**，不信任既有文档结论。每个节点的「代码现状」均给出 `file:line` 证据，如与旧文档冲突以代码为准。
>
> 审计日期：2026-07-21。

## 0. 环境与全局裁决

### 0.1 环境拓扑

- 当前 Windows `E:\skillify` **仅用于代码落盘**，不是运行/验收宿主。源码大量直接依赖 Linux/POSIX 能力（如 `src/skillify/agent/capability_lock.py:5` 的 `import fcntl`，会导致 `skillify.mcp` 等整包在 Windows 无法导入），因此真机验证一律在正式服执行。
- 正式服务器（VM）：`root@192.168.124.2 -p 2223`。
- 客户端/端侧（VM）：`fzq@192.168.124.2 -p 2222`。
- 外部依赖位于 `192.168.124.2`：DM8 `5236`、Forgejo `3000`、独立 devpi `3141`、Keycloak `18085`/`18090`、RBAC `5005`、GitNexus 隧道 `4747`。

### 0.2 全局裁决（覆盖旧文档相反要求）

1. **全项目仅 HTTP，无 HTTPS。** 内网项目、默认禁公网，接受安全降级。凡旧文档/代码要求 `https`/`tlsRequired` 的地方，一律改为允许明文 HTTP。攻击面按受控内网评估，不按公网评估。
2. **内网构件信任模型：** 系统仅用于受控内网；默认禁止公网访问；上传者与构件来源视为受信；正式构件必须有固定版本、来源和 SHA256；高风险 shell、危险权限、明文凭据、公网地址、未知二进制继续由现有规则扫描；不把“未做完整 CVE 扫描”误报为企业级供应链安全通过。
3. **半自动而非全自动。** OpenCode / Claude Code / Team 在需要用户授权放行时，允许由用户在终端手工确认，不强行绕过 agent 终端内部的权限确认。开发不追求“无人值守全自动”。
4. **codex 前置门禁职责。** 凡代码已就绪、只差真机的能力，本文列为「真机前置门禁」，由 codex 在正式服/端侧建立环境并实测，测出的缺陷再回流为开发项；不得用替身/容器测试冒充真机 `env_verified`。

### 0.3 本轮明确不做（裁决排除）

- **DM8 备份的真实恢复演练**：服务端只有单个 DM8 实例，无第二实例/镜像，无法满足“只恢复到临时实例”前提。数据库中断属不可抗力，本轮不做该风险备份方案，也不因此阻断其它节点。
- **HTTPS / TLS**：见 0.2(1)，全项目不建设。
- **Syft / Grype / Cosign 具名工具 与 完整 CVE 漏洞库**：见 T5，保留自研 SBOM+来源+SHA256+block/warn 规则，不引入三具名工具。
- **Shogun 同工作区 worker 竞争**：已用 per-worker git worktree 方案完成（见附录 A），本轮仅回归，不重做。

---

## 1. 开发任务节点

统一模板：**代码现状（证据）→ codex 需构建 → 真机前置门禁 → 验收标准**。节点按代码缺口组织，不按测试包顺序；括号内标注对应测试包。

### T1 · 能力分发与权限合并落地（TP-03）

**代码现状：**
- 事务化 pack 安装/卸载/回滚引擎已实现且有单测：`src/skillify/agent/opencode_config.py` 的 `plan_install`(:340)/`apply_install`(:1070)/`plan_uninstall`(:1107)/`apply_uninstall`(:1134)/`rollback_install`(:1167)，含目标快照恢复与 `CapabilityLock` 属主保护。
- 最严格边界权限合并已实现：`src/skillify/agent/permissions.py:671` `merge_permissions` 保留全部策略，`MergedPermissions.decide`(:655) 取 `max(restriction_rank)`，后置 allow 不能翻掉先前 deny。
- devpi 独立 docker 已完成：`infra/devpi/docker-compose.yml`（独立 project `skillify-devpi`），主 compose 仅消费 `SKILLIFY_DEVPI_INDEX_URL`（`infra/docker-compose.yml:60,79`）。
- **缺口（PARTIAL）：** 上述引擎与合并逻辑**目前只在测试内被调用**。没有任何面向用户的 `skillctl` 命令驱动 **Workflow Pack** 生命周期（`skillctl install/update/remove` 走的是 Skill 安装 `install/installer.py`，不是 pack）；没有 `update` 动词；运行期没有一处把「Skill + Workflow + MCP + 每任务」四类权限组装成一个 `merge_permissions([...])` 列表——`CapabilitySource.permissions` 只在测试里构造。

**codex 需构建：**
1. 新增驱动 Workflow Pack 生命周期的 CLI/服务入口：由已解析的 pack 构造 `CapabilitySource`，调用 `plan_install/apply_install`，并补 `update`（安装→回滚→再装或差量）与 `rollback` 动词。
2. 在任务运行期真正装配四类权限来源并喂入 `merge_permissions`，把合并结果作为该任务的最终边界下发给执行器。
3. Agent self-pull 备用下载/校验路径当前继承 Keycloak+Forgejo 可见性、无独立 agent token 边界（`docs/agent-self-pull.md` 所述、`web/service.py:22`）——如需独立 token 边界，本节点补一层专用凭据校验；否则在文档明确“备用路径不构成独立 token 边界”，不得误报。

**真机前置门禁：** 真实 Forgejo 上对一个已发布 pack 完成安装/更新/回滚/卸载，核对 checksum、版本、commit、lockfile 一致；已有 OpenCode/Claude 配置不被静默覆盖。

**验收标准：** CLI 可完成 pack 四态生命周期；运行期任务的最终权限来自四源合并且最严格边界生效（含一条“后置 allow 不能翻 deny”回归用例走真实装配路径）。

### T2 · 委派模式运行期生效（TP-05）

**代码现状：**
- 五类 pack（onboarding/bugfix/feature/review/refactor）已随仓库发布并可加载：`src/skillify/workflows/pack_config.py:91` `load_workflow_pack`；`workflows/` 根目录含五套 `skill.yaml`+`workflow.yaml`。
- 门禁/允许路径/读写/验收命令/构件声明已实现（`pack_config.py:20-25,116-201`，`tasks/work_package.py:22-33`）。
- `suggested` 生成工作包并可编辑确认已实现（`tasks/web_store.py:159-166`，`web/endpoint_agent_api.py:64-96`，前端 `web/src/views/EndpointTasksView.vue:235-251`）。
- 工作包未确认前不能领取任务已实现：`src/skillify/tasks/lease.py:37-40,54,64`（`has_unconfirmed_package` 进入候选 SELECT 与原子 UPDATE 守卫）。
- **缺口（PARTIAL）：** `adaptive`/`suggested`/`required` 已定义并校验（`pack_config.py:16,27-32`，`work_package.py:88-97` `validate_delegation_result`），但**运行期未生效**——`validate_delegation_result` 只在 `endpoint_agent_api.py:73` 用**硬编码 `"suggested"`** 调用；`dispatch_task`/runner 从不读取 pack 的 `delegation.mode`。声明 `required` 的 pack 运行期无法约束。

**codex 需构建：** 把 pack 的 `delegation.mode` 从 `load_workflow_pack` 贯穿到 dispatch/confirm，用真实声明的模式驱动 `validate_delegation_result`；`required` 约束结果（≥2 个独立工作包，非固定角色链），`adaptive` 允许运行期收敛。

**真机前置门禁：** 真实执行器上分别用声明 `required`/`adaptive`/`suggested` 的 pack 跑任务，确认最终约束符合 pack 配置。

**验收标准：** 三种模式的运行期约束各自与 pack 声明一致；存在一条“`required` pack 在只有一个工作包时被拒绝”的用例走真实 dispatch 路径。

### T3 · MCP Adapter 收口（仅 HTTP）（TP-07）

**代码现状：**
- `skillctl mcp serve` stdio server + 官方 SDK（`mcp==1.28.1`，`pyproject.toml:13`）client 往返已实现：`cli/mcp_cmd.py:17-24`、`mcp/sdk_client.py:28-64`。已注册 adapter：db-readonly、documents、forgejo、echo（`mcp/server/__init__.py:23,57`）。
- db-readonly 已实现：SELECT-only、表 allowlist、行/字节上限、敏感列 `[REDACTED]`、审计 ID（`mcp/db_readonly/connector.py:86-180`）；DM8 方言走 `USER_*` 视图（`db_readonly/dm8_executor.py:33-38`）。**弱点：** DM8 超时是**事后**判断（`dm8_executor.py:22` execute 返回后才比时间），无法中断长查询。
- Forgejo/documents adapter 已实现（`forgejo/connector.py:33-49`、`docs/connector.py:34-40`，最小 scope + allowlist）。REST adapter 已实现且**可走明文 HTTP**（`rest/adapter.py:55-67`，`http://127.0.0.1` 有单测）。
- **缺口 A：** REST adapter **未注册进 `mcp serve`**（`server/__init__.py` 无 rest），仅为独立参考类，无法经 `skillctl mcp serve` 到达。
- **缺口 B（与 0.2(1) 冲突需改）：** `remote` transport 仍**硬要求 `https` + `tlsRequired: True`**（`mcp/registry.py:595,619`），HTTP-only 部署下 remote 制品会被拒绝，等于死代码。
- **缺口 C：** adapter 的 cancel/timeout/permission-denied/unreachable/crash 只产生错误**码**（`sdk_client.py`），**未映射进任务审计事件**——`call_stdio_tool` 只被诊断命令 `mcp_cmd.py:34-51` 消费；`tasks/reporting.py:17-31` 的 `EVENT_TYPES` 无任何 MCP/adapter 事件类型。

**codex 需构建：**
1. 把 REST adapter 注册进 `mcp serve`，其目标 host/port/protocol 仅接受 manifest+本地策略共同允许集合（明文 HTTP）。
2. 放宽 `remote` transport：去掉 HTTPS/tls 硬校验，允许内网 HTTP 端点（保留 host/port allowlist 与 Bearer 注入）。
3. 建一条从 adapter 调用结果到 `record_task_event`/`EVENT_TYPES` 的桥：把取消/超时/403/不可达/崩溃转成明确、脱敏、可审计的任务事件；扩 `EVENT_TYPES` 增加对应 MCP 事件类型。
4.（可选/记录）DM8 查询超时改为可中断路径或明确记录“事后超时”限制。

**真机前置门禁：** 官方 SDK client 与真实 stdio server 完成 initialize/发现/调用/取消；db-readonly 用真实 DM8 只读账号验证方言、SELECT 限制、超时、行/字节限制、脱敏；Forgejo/documents/REST 用内网 HTTP 端点连通。

**验收标准：** 四类 adapter 均可经 `mcp serve` 到达并走 HTTP；一组故障（取消/超时/403/不可达/崩溃）各产生一条脱敏审计事件，日志与事件无凭据泄露。

### T4 · Agent App 接线（TP-10）

**代码现状：**
- `apps/*` 全部是**库代码，未接线**（仅被自身测试引用，无 web/agent/CLI 消费者）：`AgentAppContract`/`load_app_contract` 导出但无人调用（`apps/__init__.py`）。
- 本地检索边界逻辑已实现（库）：alias→目录 `resolve(strict=True)`、忽略 VCS/敏感目录、跳过 dotfile/symlink、大小上限、后缀 allowlist（`apps/local_doc_search.py:10-127`）；上传需 `confirmed=True` 且校验路径在选定目录内（:120-127）。
- CSV/文本批处理已实现新文件+变更清单，不原地覆盖源文件（`apps/file_processing.py:21-43`），但**未绑定锁定 Skill / devpi 依赖**（纯 stdlib，`PROCESSOR_VERSION` 硬编码 :14）。
- 服务端不能枚举端侧文件系统：web 仅接受已在 `endpoint.workspace_aliases` 内的 alias（`web_store.py:111`），端侧自报、服务端不列路径。
- **缺口：** TP-10 的两个非技术用户 App 表单**不在** `WORKFLOW_FORMS`（`web_store.py:22-31` 只有开发工作流）；`apps/contract.py` 的输入/输出 schema 校验未被端点调用；无“扩大目录范围”的独立确认端点。

**codex 需构建：**
1. 把本地检索、CSV 批处理作为固定表单接入 `WORKFLOW_FORMS` 与 endpoint 流（下发→端侧确认→结构化结果+审计），并调用 `apps/contract.py` 的 schema 校验。
2. CSV 批处理绑定锁定 Skill 与 devpi 依赖（走 `install/venv.py` index URL），生成新文件+预览+变更清单。
3. 新增“上传内容/扩大目录范围”的独立确认端点，绑定 alias 集合；服务端仍不枚举端侧文件系统。

**真机前置门禁：** 非技术用户仅经 Web 固定表单下发、端侧确认后执行；越界目录/上传需二次确认；源文件不被原地覆盖。

**验收标准：** 两个 App 经固定表单端到端可用；扩目录/上传均有独立确认；越界访问被 alias 边界拒绝。

### T5 · 内网构件完整性与基础风险检查（原 TP-11，改名）

> 裁决：保留自研 SBOM + 来源记录 + SHA256 校验 + block/warn 规则；**本轮不接入 Syft/Grype/Cosign，不建完整 CVE 漏洞库**。风险模型见 0.2(2)。不再以“具名三工具”为验收项。

**代码现状：**
- 自研 CycloneDX 1.5 SBOM 已实现（`security/scan.py:103-127`，`packaging/pack.py:149`）。
- 自研风险扫描器已实现且**真实分级 block/warn**：curl|sh、内嵌私钥、密钥文件、symlink、未固定依赖、过宽写权限；BLOCK 在打包期 `raise PackagingError`（`security/scan.py:16-100`，`packaging/pack.py:127-132`）。**它不是 CVE 扫描器。**
- Syft/Grype/Cosign、签名、来源证明、验证：**占位 stub**（`scan.py:46-50` 硬编码 `"status":"pending-test-env"`，全 `src/` 无三工具调用）。→ 本轮按裁决**移除该期望**。
- 评测：`aggregate_task_metrics`（`evals/metrics.py:18-63`）与 `ReplayGate.evaluate`（`evals/replay.py:29-42`）**逻辑已实现但未接真实数据**——只被 `tests/test_evals.py` 用手造 dict 调用；真实 TaskEvent 已落库（`web/app.py:928-956`）却无人喂入；publisher 新版本流程不调用 ReplayGate。
- 详情/精选页：`governance` 是作者 `skill.yaml` 的 **manifest 直通**（`web/service.py:159`，`pack.py:185`），compatibleExecutors/requiredMcp/permissions 为作者自填（mock-like）；scanStatus 真实扫描结果写在 `<name>.artifact.json`（`pack.py:164`）却**从未被索引摄取**；successRate/testPassRate 来自 manifest 非 `aggregate_task_metrics`；无 Workflow 详情页；精选条为硬编码（`FeaturedWorkflowPacks.vue:2-6`）。
- 遥测已实现且默认不含任务内容（`common/telemetry.py:43-65`，`index/events.py:13-35`）。

**codex 需构建：**
1. 保持自研 SBOM/风险扫描/block-warn；固化“正式构件必须有固定版本+来源+SHA256”的入库校验；明确文档“未做完整 CVE 扫描”不等于企业级供应链通过。
2. 把已落库的真实 TaskEvent 接入 `aggregate_task_metrics`，并在**新版本发布路径**真实调用 `ReplayGate`。
3. 详情页去 manifest 直通：把 `artifact.json` 的真实 scan 结果摄取进索引并回显 scanStatus；successRate/testPassRate 改由 `aggregate_task_metrics` 派生；compat/permission/MCP 由构件检查而非作者自填得出。补 Workflow 详情数据或明确标注“未验证”。
4. Promptfoo/Phoenix 保持占位（G8 未部署），不误报。

**真机前置门禁：** 用真实 TaskEvent 生成成功率/拒绝率/回滚率/测试通过率/阻塞原因；新版本回放门禁用真实数据；详情/精选页展示真实兼容性/权限/MCP/scan/run，不把模拟当真实。

**验收标准：** 指标与门禁走真实事件；详情页不再展示未验证的 manifest 字段为“已验证”；构件入库强制固定版本+来源+SHA256；风险扫描 block/warn 分级正确。

### T6 · OpenCode Team 结束信号兜底（TP-13）

**代码现状：** 结束信号路径 `providers/shogun.py:372-385 stream_events` → `contract.scan_queue` → `events.TeamEventMapper.map_all`，仅当出现 `TEAM_COMPLETED/FAILED/CANCELLED` 才终止。而这三类**只**由 `command` 类项在 `shogun_to_karo.yaml` 变为 `status:done/failed/cancelled` 产生（`events.py:17-19`，`contract.py:14,64-77`）。worker `task done` 只映射 `WORK_PACKAGE_COMPLETED/RUNNING`（:24），reviewer `report done` 只映射 `REVIEW_COMPLETED/RUNNING`（:25），**均非终态**。**Skillify 侧无任何代码写该文件**（grep 仅有读取），终态完全依赖外部 coordinator（LLM 驱动）自行写 `status:done`，无独立验收派生、无超时兜底 → 结构性不稳定。

**codex 需构建：** 增加 Skillify 侧终态派生：当全部工作包 `WORK_PACKAGE_COMPLETED` 且独立审查 `REVIEW_COMPLETED`（或达 Team 时长上限）时，由控制面判定终态，不再单靠外部 coordinator 写 `shogun_to_karo.yaml`；保留人工放行边界（0.2(3)），不改动上游源码，兜底逻辑放在 Skillify 适配层。

**真机前置门禁：** 全 OpenCode formation 真实任务，观测在 coordinator 未稳定写 done 时兜底能否产出规范终态+独立审查+最终验收组合。

**验收标准：** worker+review 全完成或超时的场景 100% 收敛到明确终态，事件顺序合理、按 event ID 幂等，无残留。

### T7 · Claude Code Team 人工放行（按设计，不改代码绕过）（TP-13）

**代码现状：** 启动命令硬编码 `--permission-mode default`（`config_gen.py:259`），**全源码无 `--dangerously-skip-permissions`**（仅出现在文档）。隔离 HOME 只预置 onboarding/theme/trust（`config_gen.py:224-238`），**故意不绕过工具权限确认**。真实任务在上游 `tmux display-message` 的 Bash 调用处等待人工权限确认。这是**半自动设计**：卡住原因只是没有授权，不是代码缺陷。

**codex 需构建（非绕过）：**
1. 不引入任何自动放行/`--dangerously-skip-permissions`。文档化“Claude Code Team 需用户在终端手工放行”的半自动运行模型与操作步骤。
2. per-worker WorkPackage 权限对 Claude 不可由上游公开格式表达（上游 `ashigaru` 固定角色只吃 `read_allow/deny/edit_allow/deny`，`config_gen.py:157,171-190`；工作包按枚举下标位置 zip，`shogun.py:169-173`）——如实记录此限制与其对 per-worker 隔离的影响（现已有 per-worker worktree 作互斥，见附录 A）。

**真机前置门禁（用户在场）：** 全 Claude formation 真实任务，由用户在端侧终端逐次放行权限，观测四角色启动、任务闭环、无 push 凭据、YAML/命令行/日志无明文凭据。

**验收标准：** 在用户手工放行下 formation 能完成真实任务；不存在任何代码路径自动放行；权限限制文档与代码一致。

### T8 · GitNexus 就绪探测（TP-14）

**代码现状（根因已定位）：** `skillctl codemap visualize doctor/start/status/open/stop` 已实现（`cli/codemap_cmd.py`，`codemap/visualizer.py`）。**Bug：** `visualizer.start()`（:209-229）在 `serve` 子进程 `Popen` 后**立刻**写 `CodemapStatus(...,"ready",...)`（:227），**无就绪轮询、无 `127.0.0.1:port` TCP 连接、无健康请求、无日志扫描、无超时**；`status()`（:231-244）只 `os.kill(pid,0)` 判 PID 存活。`open()` 直接拉 Chrome 到端口、前端时间线在 `start()` 一返回就发 `ready`（`codemap/task_runner.py:59-64`）。→ 端侧打开 `4747` 时 Node 服务尚未 bind/索引完成，页面停在“等待服务器启动”。可能失败点：大仓 `analyze()`（900s，:191-207）后 `serve` 未 bind、Node22/grammar 缺失导致 `serve` 于 Popen 返回后退出/挂起、`4747` 端口被占。

**codex 需构建：** 在 `start()` 写 `ready` 之前对 `127.0.0.1:port` 做就绪探测（TCP connect 或 HTTP 健康探测）并设超时；未就绪则状态置 `starting`/失败并写明原因（读 `gitnexus.log`）；`open()` 前确认 `ready`。前端时间线改为真实就绪后才显示 `ready`。

**真机前置门禁：** 端侧批准 Node22 + Chrome 上 `start/status/open` 全链路：服务真正 bind 后才 `ready`，Chrome 能打开目录/图谱；断网核心图谱仍可用；无公网请求。

**验收标准：** 服务未就绪时不会误报 `ready`；就绪探测超时给出明确原因；端侧不再出现“等待服务器启动”悬挂；`stop` 幂等无残留进程。

### T9 · 真机全链路前置门禁（TP-00 / TP-06 / TP-12 / TP-13）

> 这些能力**代码已就绪**，缺的是真机验证。codex 在正式服/端侧建立环境实测，测出缺陷再回流为开发项。

- **TP-00 SkillHub 回归（代码就绪，见 T 无缺口项）：** Git tag webhook 打 tag 入库（`webhook/handler.py:71`）、全量/单仓索引重建（`index/rebuild.py`，`skillctl rebuild-index`）、Release 中断恢复（`publish/publisher.py:117` draft→补传缺失 asset）、三发布入口重复/冲突版本行为（`AlreadyPublishedError`）——在真实 Forgejo 上跑通并销账。
- **TP-06 控制面（代码就绪）：** 真实 Keycloak/RBAC 下 Bridge 出站拉取/续租/心跳/上报、Outbox 断网补传不重复、标准事件、固定表单无任意 prompt/shell、事件脱敏——真机验证。
- **TP-12 双执行器全链路：** 无单一代码工件覆盖“Web 创建→真实端侧拉取→真实 OpenCode/Claude 执行→事件回传 Web”，其本质是真机测试（组件级 `tests/test_endpoint_agent_api.py`、`tests/test_bridge_runner.py` 已覆盖分段）。OpenCode 与 Claude 各跑一次真实全链路。
- **TP-13 formation：** 依赖 T6（OpenCode 兜底）与 T7（Claude 人工放行）完成后，跑两类 formation 的取消/崩溃/重启恢复/无秘密审计/无残留。

**验收标准：** 每项给出真实任务 ID/Endpoint ID/事件 ID/工作包 ID、脱敏日志、无公网访问与无残留进程证据，结论只用 `passed/failed/blocked/not-run`，不用“基本通过”。

---

## 附录 A · 已完成，仅回归（不重做）

- **Shogun 同工作区 worker 竞争 → 已用 per-worker git worktree 解决。** 证据：`src/skillify/agent/shogun/worktree.py`（`create` 从冻结 `base_commit` 每 worker 一 worktree + 集成 worktree，:144-235；`.skillify-team-owner` 标记 + `extensions.worktreeConfig=true` + owner marker 排除出 git status，:102-176；`cleanup` 三重安全校验，:297-332）；`integration.py`（`--no-ff` 由 Integration 角色合并，保留冲突）；`team_recovery.py`/`providers/shogun.py:264-356`（重启只读诊断与安全清理）。近提交 `f15b82a c0596b0 fda6ea2 d5739c5 c1ed094 5e1615e`。回归点：真机确认每 pane 实际运行在其 `SKILLIFY_WORKTREE`（配置只导出 env，`cd` 依赖上游运行时）。
- **devpi 独立 docker → 已完成。** `infra/devpi/docker-compose.yml`；主栈仅消费 index URL。
- **TP-04 CodeGraph / TP-08 Credential Broker** 在旧交付文档已 `passed`，本轮不列开发项。

## 附录 B · 排除项（本轮不做，见 0.3）

- DM8 备份真实恢复演练（单实例不可抗力）。
- HTTPS/TLS（全项目 HTTP）。
- Syft/Grype/Cosign 具名工具与完整 CVE 库（保留自研检查，T5）。

## 附录 C · 来源

- 测试交付：`docs/testing/2026-07-17-post-ba3-test-environment-handoff.md`
- 需求/历史：`docs/2026-07-16-endpoint-agent-tasks.md`、`docs/2026-07-16-skillify-agent-architecture-convergence-task.md`、`docs/2026-07-16-skillify-endpoint-mcp-and-agent-delegation-task.md`、`docs/2026-07-18-skillify-shogun-team-runtime-task.md`、`docs/2026-07-19-skillify-codemap-visualization-task.md`、`docs/agent-self-pull.md`
- 本文代码证据均来自审计时 `main`（`06af983`），如与来源文档冲突以代码为准。
