# 项目代码关系可视化（服务端 GitNexus）开发计划与任务节点

> 用途：交给 Codex/Claude 开发窗口执行。产品方向：把「用户侧代码关系可视化」从**端侧本地运行 GitNexus** 改为**端侧本地 Git 提交 → 打包 → 上传服务端 → 服务端独立 Docker 运行 GitNexus → 浏览器经 Skillify 鉴权查看**的单一入口。
>
> 生成依据：`main` 源码审计（审计时 `06af983`），**不信任既有文档结论**。每处「现状」均给出 `file:line` 证据。
>
> 审计日期：2026-07-21。本轮**只产出计划与任务节点，不改代码**。

---

## 0. 全局裁决与不可触碰边界

### 0.1 环境拓扑
- Windows `E:\skillify` **仅代码落盘**，非运行/验收宿主（源码大量依赖 Linux/POSIX，如 `agent/capability_lock.py:5` `import fcntl`）。真机验证一律在目标 VM 执行。
- 正式服务器（VM，麒麟）：`root@192.168.124.2 -p 2223`，运行 Docker 栈。
- 客户端/端侧（VM）：`fzq@192.168.124.2 -p 2222`，运行 Endpoint/bridge。
- 全项目仅 HTTP，无 HTTPS/TLS（受控内网，接受安全降级）。凭据不得写入任何文档/日志。

### 0.2 不可触碰边界（**最高优先级，覆盖一切"适配"冲动**）

**「codemap 交付 agent」是当前项目核心，冻结，本计划任何任务都不得修改。** 命名易混淆，按文件路径锁定：

| 名称 | 实际模块 | 索引目录 | 面向 | 本轮 |
|---|---|---|---|---|
| **Agent 侧核心代码图 = CodeGraph** | `src/skillify/agent/codegraph.py`；MCP 工具 `codegraph_explore` | `.codegraph/` | opencode/claude/shogun **agent** | **冻结，禁止改动** |
| 用户侧附属展示 = GitNexus | `src/skillify/codemap/`（`visualizer.py`/`task_runner.py`） | `.gitnexus/` | 用户浏览器查看 | 本轮改造对象 |

**冻结清单（任一改动都视为违规）：**
1. 不得修改 `agent/codegraph.py` 及 CodeGraph 清单 `infra/offline/codegraph-manifest.json`。
2. 不得修改 CodeGraph 的 MCP 接线：`cli/bridge_cmd.py:366-372`、`agent/opencode_config.py:1213-1235`、`agent/claudecode_config.py:17-49`。
3. 不得修改 `tasks/web_store.py:184`（agent 工作流 `recommended_mcp=["codegraph"]`、codemap 工作流 `[]` 的分流逻辑）。
4. GitNexus 服务端改造必须与 CodeGraph **完全独立**，不得为"适配上传/Docker"去改 codemap↔agent 交互能力。GitNexus 因当前**无任何 agent 交互**（codemap 工作流 `recommended_mcp=[]`，见 `web_store.py:184`），本改造在结构上不会触及 agent，前提是遵守本清单。

### 0.3 架构硬边界（用户裁定）
- **单一入口**：全部走「端侧本地 Git 提交 → 打包 → 上传服务端」。不建临时 Forgejo 仓库；不引入 MinIO（复用现有文件系统 `cache_dir` 约定）；对外仍是单一上传流程。
- GitNexus Docker **只装 GitNexus 自身运行环境**（Node22/OpenSSL3/LadybugDB/FTS/grammar），不安装被分析项目的 Python/Node/Java/C# 业务依赖。
- 源码目录与索引目录**按 task 隔离**；容器不得看到宿主机项目根或其它 task 目录；源码挂载**默认只读**。
- **不向普通用户暴露** GitNexus 的 MCP/Shell/改码/Agent 能力；用户不能经 GitNexus 改代码、执行命令或访问其它项目。
- 不扩成通用制品平台 / Git 托管 / 企业级供应链平台。GitNexus 只做静态索引 + 调用关系 + 可视化，不负责运行/编译/测试用户项目。

### 0.4 状态定义（贯穿全部任务的验收口径）
- **implemented**：代码已写、单测通过、可在开发机/CI 跑；**不代表真机可用**。
- **dev_verified**：开发者在开发环境（可含容器替身、SQLite、非麒麟 OS）端到端跑通、逻辑正确；仍非目标真机。
- **env_verified**：在**目标麒麟服务器 / 端侧 VM 真机、断网、真实依赖**下端到端通过，产出真实 task_id / 事件 ID / 索引 ID 等可复现证据。**Phase 1 门禁只认 env_verified，不接受 stub/mock/仅单测冒充。**

---

## 1. 当前相关代码与基础设施现状（证据）

### 1.1 现状与新方向相反：GitNexus 今天在端侧本地跑，无 Docker
- `codemap/visualizer.py` 以**端侧本地 `node` 子进程**运行 GitNexus：`analyze`（`:238-266`）与 `serve --host 127.0.0.1 --port 4747`（`:284-288`）均为 `Popen`；源码来自 `shutil.copytree` 的端侧工作区快照（`:226-236`，忽略 `.git/.gitnexus/.venv/node_modules/__pycache__/.pytest_cache`）。
- **运行路径无任何 Docker**。`infra/gitnexus-test/Dockerfile`+`docker-compose.yml` 存在，但**仅测试/评测用**，未被任何运行代码引用；清单 `infra/offline/gitnexus-visualizer-manifest.json:22-27` 描述 `containerImage`/`containerArchive` 但**无代码加载**。
- CLI：`skillctl codemap visualize {start,status,open,stop,doctor}`（`cli/codemap_cmd.py:43-73`），需环境变量 `SKILLIFY_GITNEXUS_ROOT`（`:25-27` 必填）、`SKILLIFY_GITNEXUS_MANIFEST`。
- 就绪探测：`start()` 已在 `Popen` 后对 `(bind_host,port)` 做 TCP 就绪轮询、超时 30s（`visualizer.py:296-322`）。**注意**：这与旧 `2026-07-21-post-ba3-followup-dev-tasks.md` 的 T8「无就绪探测」结论**冲突**——以当前代码为准，就绪探测已存在。服务端化后该逻辑需迁移/重写为对容器的健康探测。
- 端侧触发链：前端 `EndpointTasksView.vue:180-199`（"LOCAL CODE ATLAS"）→ `runCodemapAction`（`:121-140`，`workflowId=codemap.visualization.<action>`，`runtime='codemap'`）→ bridge 拉取 → `codemap/task_runner.py:34-73` → visualizer。

### 1.2 上传管道不存在（四处净新增）
- 端侧↔服务端只有**拉取式任务 + 闭包 JSON 事件**：`HttpBridgeTransport`（`cli/bridge_cmd.py:67-120`）仅 `pull`/`confirm`/`confirm_scope`；事件仅 `POST /api/endpoint/events`（`tasks/reporting.py:164`）。
- **任务参数禁止源码**：`tasks/protocol.py:126-128` 的 `_FORBIDDEN_PARAMETER_KEYS` 含 `source`/`source_code`。
- **所有 `UploadFile` 路由都是浏览器 Keycloak 专用**（`require_keycloak_user`）：`app.py:786`（skill zip）、`:558`、`:675`；端侧路由（`endpoint_agent_api.py`）全为 JSON，无 endpoint-HMAC 上传路由。
- `packaging/pack.py` **排除 `.git`**（`:22`）且强制 `skill.yaml`（`:115-119`）+ 安全扫描门禁（`:123-132`），**不能直接复用于源码快照**；可复用原语仅 `build_tarball`（`:86-102`，可复现 tar）与 `sha256_file`（`:105-110`）。
- 服务端**不把上传解压到 per-task 目录**：仅有 skill build 的 per-build 工作区（`web/upload_service.py:26-56` copytree 到 `record.workspace`；`web/formal_publish.py:47-48,136` 到 `cache_dir/formal-publish/<id>`）。任务记录 `EndpointTaskRecord`（`index/models.py:238-267`）无文件暂存区。
- 端侧已有可复用原语：clean-workspace + HEAD 解析（`bridge_cmd.py:322-338`，产出 `base_commit` + workspace `Path`，当前仅 shogun team 用）。

### 1.3 服务端从不启容器；离线 Docker 底座已 ~80%
- **服务端无编程式 Docker**：`src/` 无 `/var/run/docker.sock` 挂载、无 docker-py（`pyproject.toml` 无 `docker`），唯一 `docker` 字样是 `doctor_cmd.py:133` 提示串。→ "服务端按 task 启容器"是净新增能力。
- 主栈 `infra/docker-compose.yml`（`name: skillify`）5 服务：`db`(postgres 内部)、`forgejo`、`webhook`(8088)、`skillify-web`(**8089，不发布到宿主**，仅内部 `skillify` 网络经 Nginx 反代)、`frontend`(nginx，宿主 8080)。DM8/Keycloak/RBAC/devpi 为外部服务，仅以 env URL 引用。
- **离线底座已成型**（Phase 1 应演进而非重建）：`infra/gitnexus-test/Dockerfile` 已固定 `node:22.23.1-bookworm-slim`、装 `libssl3`、`@ladybugdb/core` install、离线 grammar 构建、剥离 google fonts；compose 用 `internal: true` 无出网网络 + 固定子网 `172.24.0.0/16`；清单含可 `docker load` 的镜像 tar + SHA256（`infra/offline/gitnexus-visualizer-manifest.json:24-27`）。**当前缺口**：挂载是 `:rw`（`docker-compose.yml:11-12`）、`serve` 绑 `0.0.0.0`（`Dockerfile:40`，内部网可接受）、按 alias 而非 task 隔离、未被产品代码驱动。
- Nginx 反代模式已在用：`web/nginx.conf:17` `/api/`→`skillify-web:8089`；`:25` `/rbac-api/`→ host RBAC。

### 1.4 GitNexus 确实把源码复制进快照与索引
- Skillify 先 `copytree` 全量复制源码到 `<state>/<alias>/workspace/`（`visualizer.py:226-236`）。
- GitNexus `analyze --index-only` 在快照内生成 `.gitnexus/`（LadybugDB/FTS），代码断言其存在（`visualizer.py:264-265`）；索引与源码副本**同目录**，删除 task 目录可原子回收二者。
- **保留规则据此确定**：索引为源码派生物、含源码派生数据，必须随 task 删除同销毁；Phase 1 仍须**真机核验** `.gitnexus/` 具体内容（是否含源码正文/片段），落地保留/删除规则。

### 1.5 鉴权、数据模型、前端现状
- 鉴权双面：浏览器 Keycloak JWT `require_keycloak_user`（`web/auth.py:69`）；端侧 HMAC `require_endpoint_machine`（`web/endpoint_auth.py:19-33`）。对象级授权为**各 handler 内联 `owner_username` 校验**（`endpoint_agent_api.py:35-39`、`tasks/web_store.py:121-123`），无统一中间件。
- **无"项目"实体**：最接近的归属维度是 `EndpointBinding.owner_username` + `workspace_aliases`（`index/models.py:225-235`）与 `EndpointTaskRecord.owner_username`（`:238-267`）。"项目"仅存在于外部 RBAC（`X-Project: skillify` 常量）。
- 数据层：ORM 集中于 `index/models.py`（14 表，`Base` `:18`）+ 手工编号 `infra/dm8-init/NN-*.sql` **expand-only** 迁移；新增表 = 新 ORM 类 + 新编号 SQL。
- 事件：`tasks/reporting.py:18-34` `EVENT_TYPES`（含 `codemap.visualization.*` 10 项与 `mcp.adapter.*` 5 项）；`record_task_event`（`web_store.py:325-393`）按 `event_id` 幂等、映射终态。
- 前端：路由由 RBAC `06-rbac-skillify-menus.sql` 动态注入；**iframe 渲染当前被关闭**（`web/src/router/dynamicRoutes.js:37` "contract reserved, not rendered"）。无嵌入渲染页先例（仅 `<a target=_blank>` 开 Forgejo release）。任务无轮询（`EndpointTasksView.vue:167` 仅 onMounted 一次）。
- 重启恢复：web 无 FastAPI startup/lifespan 钩子；靠租约过期（`tasks/lease.py:50-56`）+ 信封幂等（`web_store.py:199-200`）+ 事件幂等自愈。

---

## 2. 推荐目标架构

```
端侧 fzq VM                              服务端 root VM (Docker, 内网 HTTP)
──────────                              ─────────────────────────────────
工作区 @ 已提交 HEAD                      /srv/codemap/tasks/<task_id>/
  ├ 复用 bridge_cmd.py:322 clean-WS+HEAD   ├ source/   ← 解压, 容器 :ro 挂载
  ├ git-tracked 文件 → 可复现 tar          └ index/    ← 容器可写, 落 .gitnexus
  └ + SHA256                              index 容器: skillify/gitnexus:<ver>
        │ (前端派发 codemap 快照任务,          (离线, internal 网, 无 egress,
        │  bridge 生成并上传)                  只装 GitNexus 自身环境)
        ▼                                   索引完成即退出; 查看时起 serve 容器
  新增 endpoint-HMAC 上传路由  ──────────▶  skillify-web 内鉴权反代 (task 归属校验)
  POST /api/endpoint/codemap/upload           → 前端项目空间 iframe 内嵌
```

**要点：**
- 隔离键 = `task_id`（新增服务端 per-task 目录），非 alias。
- 一个**索引容器**跑完 `analyze` 落 `index/` 后退出；**serve 容器**按需/查看会话临时起、挂 `source(:ro)+index`、空闲销毁（索引持久化在磁盘，serve 无状态）。
- 鉴权反代放在 **skillify-web（FastAPI）内**而非静态 Nginx：因为 per-task 容器是动态上游，且鉴权+task 归属校验本就内联在此层（复用现有 `owner_username` 内联模式），由它把 `task_id→容器 host:port` 映射后代理；前端 iframe 指向该受控路径。
- 上传/存储复用文件系统 `cache_dir` 约定，不引入 MinIO；不建临时 Forgejo。

---

## 3. 涉及模块、新增模块、主要数据流

**复用（不改核心逻辑，仅接线/扩展）：** `bridge_cmd.py`（clean-WS+HEAD、传输层）、`tasks/reporting.py`（事件）、`tasks/web_store.py`（任务分发/事件记录，**除 :184 冻结行**）、`web/endpoint_auth.py`（HMAC）、`web/auth.py`（Keycloak）、`index/models.py`+`dm8-init/`（数据层模式）、`packaging/pack.py` 的 `build_tarball`/`sha256_file` 原语、`web/nginx.conf` 反代模式、`infra/gitnexus-test/`（Docker 底座）。

**新增：**
- 端侧：源码快照打包器（git-tracked → tar+SHA256）、上传客户端方法、`skillctl codemap snapshot`（Phase 1 独立入口）。
- 服务端：per-task 目录编排器、Docker 运行封装（`docker run/rm`，内部网、`:ro` 源码）、索引任务与 serve 编排、鉴权反代路由、上传接收路由（endpoint-HMAC）。
- 数据：`codemap_snapshot`/`codemap_index_task` 表（ORM + 编号 SQL）。
- 前端：项目空间"代码关系"入口 + 状态/进度 + iframe 嵌入。

**主要数据流（Phase 2 正式态）：** 前端"代码关系→重新索引" → 派发 codemap 快照任务 → bridge 检测已提交/打包/上传（endpoint-HMAC）→ 服务端建 `tasks/<id>/source` → 起索引容器落 `index/` → 事件回传（复用 `EVENT_TYPES`，扩 upload/index/delete 类型）→ 前端轮询状态 → ready 后经鉴权反代 iframe 查看 → 删除任务销毁 source/index/容器。

---

## 4. API / 数据模型 / 前端 大方向

**API（HTTP，内网）：**
- `POST /api/endpoint/codemap/upload`（endpoint-HMAC，multipart：tar + sha256 + task 元数据；大小上限沿用 `common/config.py:187-189` 或新设 codemap 专用上限）。
- `POST /api/endpoint-tasks/<id>/codemap/index`（触发索引）、`GET .../codemap/status`（Keycloak，查询上传/排队/索引/ready/failed/expired）、`DELETE .../codemap`（清理）。
- `GET /api/codemap/<task_id>/view/**`（Keycloak + task 归属校验，鉴权反代到 serve 容器）。

**数据模型（新表，expand-only）：** `codemap_snapshot`（snapshot_id、owner_username、endpoint_id、workspace_alias、commit、sha256、size、created_at、state）、`codemap_index_task`（index_id、snapshot_id、task_id、container_ref、index_dir、state、error、created/updated_at、expires_at）。归属键 `owner_username`；状态机：`uploading→queued→indexing→ready / failed / expired`。

**前端：** 在**项目空间**内以"代码关系"入口呈现——推荐扩展 `EndpointTasksView.vue` 现有 codemap-card（`:180-199`）或新增一条 RBAC 菜单（`06-rbac-skillify-menus.sql` MERGE 幂等）。展示上传进度/排队/索引中/成功/失败/过期；ready 后 iframe 内嵌鉴权反代路径（需打开 `dynamicRoutes.js:37` iframe 渲染或走后端代理路由）；重新提交→重新快照+重新索引；旧索引替换/保留/清理提示。**不新建独立产品入口**。

---

## 5. Phase 1：独立 Docker 与真实上传验证门禁（先做，硬门禁）

> 目标：与正式业务**低耦合**的真实、可重复技术验证入口，证明方案在目标麒麟服务器稳定运行。**不要求提前完成产品界面**。全部产物需 **env_verified** 才算过。

| ID | 任务 | 验收（env_verified 口径） |
|---|---|---|
| **P1-1** | 由 `infra/gitnexus-test` 演进出**离线服务端镜像** `skillify/gitnexus:<ver>`：内含 Node22/OpenSSL3/LadybugDB/FTS/grammar 及全部依赖；不依赖麒麟宿主 OpenSSL/Node/业务语言；断网构建；产出 `docker load` tar + SHA256。 | 目标服务器**断网** `docker load` + 起容器成功；`node --version`≥22、libssl3、LadybugDB/FTS 可用；镜像不含被分析项目业务运行时。 |
| **P1-2** | 端侧**快照打包器**：git 已提交 → 仅追踪文件 tar + SHA256；复用 `bridge_cmd.py:322` clean-WS+HEAD；**不复用** `pack_skill`（排除 `.git`/强制 skill.yaml）。独立 `skillctl codemap snapshot`。 | 端侧对真实项目提交后生成 tar，SHA256 可校验；未提交/脏工作区被拒；不含忽略目录。 |
| **P1-3** | 服务端**最小上传验证入口**（临时 route，接 tar+SHA256、校验、解压到 `/srv/codemap/tasks/<task_id>/source/`）。低耦合，可不接完整前端鉴权，但须有基本 token。 | 上传→校验→解压成功；SHA256 不符/超限被拒；解压路径受限（防目录穿越）。 |
| **P1-4** | 服务端**按 task 起独立 source/+index/**；容器 `:ro` 挂 source、可写挂 index；`docker run` 内部网、无 egress；完成真实索引。 | 索引真实产出 `.gitnexus/`；source 只读（容器内写 source 失败）；容器无出网。 |
| **P1-5** | **浏览器查看**（经反代或直连测试端口）：文件、符号、函数/方法调用关系、源码行号；**Py/Java/C#/JS-TS-Vue** 各用代表性仓库；全程断网。 | 四类语言代表仓库各自可浏览文件/符号/调用关系/行号；断网无公网请求。 |
| **P1-6** | **多项目隔离 + 清理**：source/index/容器不串用；删除 task 后 source、临时 Git、index、容器资源按设计清理。 | 两 task 并存互不可见；删除后磁盘与容器资源归零，无残留进程/卷。 |
| **P1-7** | **索引内容核验**：明确 GitNexus 是否把源码正文/片段复制进 `.gitnexus/`，据此定索引保留/删除规则。 | 给出 `.gitnexus/` 内容实测结论 + 成文保留/删除规则。 |
| **P1-GATE** | **门禁**：P1-1..P1-7 全部 env_verified 于目标麒麟服务器，方可进入 Phase 2。失败记录真实原因并**停止前后端扩展**，不得以 stub/mock/仅单测冒充完成。 | 出具真机证据（task_id、镜像 SHA256、断网证明、清理证明）；任一未过则 Phase 2 阻断。 |

---

## 6. Phase 2：Skillify 前后端正式接入（门禁通过后）

| ID | 任务 | 验收 |
|---|---|---|
| **P2-1** | 数据模型：新增 `codemap_snapshot`/`codemap_index_task`（ORM `index/models.py` + 编号 `dm8-init/NN-*.sql` expand-only）；归属 owner+endpoint+alias；状态机。 | 表建成、幂等迁移；归属与状态字段齐备；单测覆盖状态流转。 |
| **P2-2** | 端侧接入：本地提交检测 + 快照打包 + 上传，走**任务驱动**（前端派发 codemap 快照任务 → bridge 生成并经**新增 endpoint-HMAC 上传路由**上传）。 | 前端一键触发→端侧打包上传→服务端收妥；HMAC 校验；断网 outbox 补传不重复。 |
| **P2-3** | 服务端 API：上传/状态查询/索引/删除（endpoint-HMAC + Keycloak 双面）；上传进度/排队/索引中/成功/失败/过期状态机。 | 各 API 鉴权与归属校验正确；状态机与事件一致；越权 404。 |
| **P2-4** | **鉴权反代 + 嵌入**：skillify-web 内把 per-task serve 容器反代到经 Skillify 身份+项目权限校验的路径；前端 iframe 内嵌；用户不能直连容器/跨项目/改码/执行命令。 | 反代仅对归属者放行；跨 task/越权被拒；GitNexus MCP/Shell/改码能力不可达。 |
| **P2-5** | 前端：项目空间"代码关系"入口（扩展 `EndpointTasksView` codemap-card 或新增 RBAC 菜单）；进度/状态展示；重新提交→重快照+重索引；旧索引替换/保留/清理策略。 | 端到端可用；重索引替换旧索引；无独立新产品入口。 |
| **P2-6** | 服务重启后任务恢复（现无 startup 钩子 → 定恢复策略：租约/启动扫描其一）；上传中断/索引失败/容器异常/删除失败处理。 | 重启后在制任务收敛到明确态；四类异常各有处理路径与事件。 |
| **P2-7** | 审计与项目级操作日志：复用 `record_task_event`；扩 `EVENT_TYPES` 增 codemap 上传/索引/删除事件类型；脱敏无凭据。 | 关键操作可审计、按 event_id 幂等、无凭据泄露。 |

---

## 7. 关键风险 / 依赖 / 回退

- **风险 R1（就绪探测语义迁移）**：现端侧 `visualizer.py:296-322` 的 TCP 就绪探测需重写为对**容器**的健康探测（容器起 ≠ 服务 bind ≠ 索引完成）。回退：状态置 `indexing/failed` 并写明原因，不误报 ready。
- **风险 R2（动态上游反代）**：per-task 容器动态端口/IP，静态 Nginx 不够 → 反代逻辑须在 skillify-web 内按 task 映射。回退：先 `<a target=_blank>` 经反代打开，暂不 iframe。
- **风险 R3（离线依赖漂移）**：LadybugDB/FTS/grammar 曾需临时联网装（见测试文档）。P1-1 必须把其全部固化进镜像并断网验证；否则门禁不过。
- **风险 R4（源码/索引残留）**：source+index 含源码派生数据；删除失败=数据残留。P1-6/P2-6 强制清理校验。
- **风险 R5（冻结边界误伤）**：任何对 `codegraph.py`/`codegraph_explore` 接线/`web_store.py:184` 的改动即违规 → CI/评审须显式检查 diff 不含这些路径。
- **依赖**：目标服务器 Docker 可用、离线镜像可 `docker load`；端侧 git 可用；Keycloak/HMAC 密钥已配置（不入库文档）。
- **总回退条件**：P1-GATE 未过 → 停止 Phase 2、记录真实原因、保留端侧本地 GitNexus 旧路径（`skillify.codemap` 现状）作为临时可用能力，不删除。

---

## 8. 分阶段 Plan（顺序）

1. Phase 1：P1-1 → P1-2 → P1-3 → P1-4 → P1-5 → P1-6 → P1-7 → **P1-GATE（真机门禁）**。
2. 门禁通过后 Phase 2：P2-1 → P2-2 → P2-3 → P2-4 → P2-5 → P2-6 → P2-7。
3. Phase 2 完成后再评估**是否退役端侧本地 GitNexus 路径**（`skillify.codemap` 端侧 runtime）；**该退役不得触碰 CodeGraph**（0.2 冻结清单）。

---

## 9. Task 清单（可逐项执行）

每项交付需标注 `implemented / dev_verified / env_verified`（定义见 0.4）。Phase 1 全部要求推进到 **env_verified**；Phase 2 至少 `dev_verified`，涉真机的（P2-2/P2-4/P2-6）需 `env_verified`。

- [x] P1-1 离线服务端镜像（env_verified，2026-07-21）：由已构建的 `skillify/gitnexus-test:1.6.9`（root@目标服务器，CentOS 7，非文档所称"麒麟"——麒麟实为端侧 fzq VM，见附录 A 更正）`docker tag` 为 `skillify/gitnexus:1.6.9`；`docker save`+gzip 产出 `/opt/skillify/offline/codemap/gitnexus/1.6.9-prod/skillify-gitnexus-1.6.9-image.tar.gz`，SHA256 `35a465e7f6673ebc820c9062cd06f187ebb842208ce5b68d297a2f27316c102d`（`sha256sum -c` 校验 OK）；`docker load` 回灌成功；`--network none` 下容器可运行：`node --version`→v22.23.1，`openssl version`→OpenSSL 3.0.20，`@ladybugdb/core` 模块存在，tree-sitter 语法（java/cpp/go/c-sharp 等）存在；镜像内 `which python/python3/java/dotnet` 均未找到（不含被分析项目业务运行时）。
- [x] P1-2 端侧快照打包器 + `skillctl codemap snapshot`（implemented, dev_verified on Windows 2026-07-21；env_verified 待端侧 fzq VM 实测）：`src/skillify/codemap/snapshot.py`（`build_snapshot`：clean+HEAD 校验、`git ls-files -z` 仅打包已追踪文件、可复现 tar、SHA256）+ `skillctl codemap snapshot --workspace <alias> --output <dir>` CLI；4 个单测覆盖脏工作区拒绝/非 git 仓库拒绝/仅打包追踪文件/可复现性，本地全绿。刻意不依赖 `packaging.pack`（该模块经 `mcp`/`agent` 链引入 `fcntl`，仅 POSIX 可用，见附录 A 更正）。
- [x] P1-3 服务端最小上传验证入口（implemented, dev_verified on Windows 2026-07-21；env_verified 待服务器实测）：`src/skillify/codemap/upload_verify.py`（task_id 白名单校验、SHA256 校验、tar 成员逐一校验后再解压——拒绝符号链接/硬链接/绝对路径/`..`穿越）+ `src/skillify/codemap/upload_server.py`（独立 FastAPI app，`POST /codemap/upload`，Bearer token，大小上限，`python -m skillify.codemap.upload_server` 可独立运行）；15+7 个单测覆盖鉴权/校验和不匹配/task_id 非法/超限/路径穿越，本地全绿。
- [x] P1-4 per-task 目录 + `:ro` 挂载 + 索引容器（implemented, dev_verified on Windows 2026-07-21；env_verified 待服务器实测）：`src/skillify/codemap/index_orchestrator.py`（`IndexOrchestrator.index(task_id)`：构造 `docker run --rm --network <internal> -v source:/workspace:ro -v index:/workspace/.gitnexus -w /workspace <image> analyze --skip-git --index-only ...`；source 目录不存在/`task_id` 非法/容器非零退出/index 目录空均拒绝并给出详情；`python -m skillify.codemap.index_orchestrator <task_id>` 可独立运行）；5 个单测（含伪造 docker 命令验证 `:ro`/网络参数正确性）本地全绿。
- [ ] P1-5 四语言代表仓库断网浏览（env_verified；现状核验 2026-07-21：服务器 `/opt/skillify/offline/codemap/eval/` 已有 `flask-3.1.3.tar.gz`（Python）与 `element-plus-2.14.0.tar.gz`（JS/TS/Vue）；**Java、C# 代表仓库缺失**，未在服务器任何路径找到——P1-5 执行前需先离线准备这两类代表仓库）
- [x] P1-6 多项目隔离 + 删除清理（implemented, dev_verified on Windows 2026-07-21；隔离性由 per-task_id 目录 + `validate_task_id` 白名单构造保证——已在 P1-3/P1-4 单测覆盖；本任务新增 `src/skillify/codemap/task_cleanup.py`：`remove_task(tasks_root, task_id)` 幂等删除整个 task 目录，`python -m skillify.codemap.task_cleanup <task_id>` 可独立运行；4 个单测覆盖删除/幂等/非法 task_id/不误删同级 task，本地全绿。容器清理未新增代码——P1 索引容器为 `docker run --rm`，退出即自动回收，无需额外清理；env_verified 待服务器实测两 task 并存 + 删除后磁盘/容器归零）。
- [x] P1-7 `.gitnexus/` 内容核验 + 保留/删除规则（env_verified，2026-07-21，基于服务器已有的 flask 测试索引 `/opt/skillify-test/gitnexus-state/flask/workspace/.gitnexus/`）：**结论：GitNexus 把源码正文逐字复制进索引**。证据：该 `.gitnexus/` 目录 53M，对应源码仅 2.5M（≈20 倍膨胀）；核心存储 `lbug`（LadybugDB，48.7M 二进制）用 `strings` 检出与 Flask 实际源码/文档逐字一致的大段文本（含完整 docstring、注释、示例代码），非仅 AST 元数据；旁路 `parse-cache/*.json` 则是纯结构化图节点（`filePath`/`startLine`/`endLine`/`language` 等属性，不含正文，用于符号/调用关系）。**保留/删除规则（据此确定）**：`.gitnexus/`（含 `lbug`、`parse-cache`、`parsedfile-cache`）视为源码衍生且含源码正文的数据，**必须与 `source/` 同生命周期**——task 删除时两者必须原子清理，不得只删 `source/` 保留 `index/`（否则残留的源码正文经索引泄露）；不得跨 owner/task 共享或缓存复用同一份索引。（env_verified）
- [ ] **P1-GATE 真机门禁复核（阻断 Phase 2）**
- [ ] P2-1 数据模型 + 迁移
- [ ] P2-2 端侧提交检测/打包/上传（任务驱动 + endpoint-HMAC）（env_verified）
- [ ] P2-3 上传/状态/索引/删除 API
- [ ] P2-4 鉴权反代 + iframe 嵌入（env_verified）
- [ ] P2-5 项目空间"代码关系"入口 + 重索引/清理策略
- [ ] P2-6 重启恢复 + 四类异常处理（env_verified）
- [ ] P2-7 审计与操作日志 + 事件类型扩展

---

## 附录 A · 与既有文档的冲突记录（以代码为准）
- 旧 `docs/2026-07-21-post-ba3-followup-dev-tasks.md` T8 称 GitNexus `start()` "无就绪探测即写 ready"；**当前代码 `visualizer.py:296-322` 已有 TCP 就绪探测**。服务端化后需改为容器健康探测，非"补一个不存在的探测"。
- 0.1 环境拓扑称服务器（root@…2223）为"麒麟"，**真机核验（2026-07-21）与此相反**：`root@192.168.124.2:2223` 实为 **CentOS Linux 7**（`3.10.0-1160.71.1.el7.x86_64`）；**麒麟 V10 SP1** 实际是端侧 `fzq@192.168.124.2:2222`（`fzq-pc`，无 Docker，符合"端侧仅跑 Endpoint/bridge"定位）。后续文档/任务中的"目标服务器"均指 CentOS 7 该机，"麒麟"应仅指端侧。

## 附录 B · 来源
- 需求方向：本轮用户裁定（单一入口、两阶段门禁、冻结 CodeGraph、HTTP-only、不引 MinIO/临时 Forgejo）。
- 代码证据：审计时 `main`（`06af983`）——`src/skillify/codemap/*`、`src/skillify/agent/codegraph.py`、`src/skillify/cli/{codemap_cmd,bridge_cmd}.py`、`src/skillify/web/*`、`src/skillify/tasks/*`、`src/skillify/index/models.py`、`infra/{docker-compose.yml,gitnexus-test/*,offline/*,dm8-init/*}`、`web/src/*`。
- 历史：`docs/2026-07-19-skillify-codemap-visualization-task.md`、`docs/testing/2026-07-17-post-ba3-test-environment-handoff.md`。
