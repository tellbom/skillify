# 评审结论：M2–M6（Opus 4.8）

> 评审对象：Skillify M2（发布流水线+索引）/ M3（Web 目录）/ M4（上传+Keycloak 登录）/ M5（评论+排行榜）/ M6（预留接口），Sonnet 5 实现。
> 评审人：Opus 4.8（3 个并行子评审 agent 逐文件通读 + Opus 亲自复核 auth/upload/前端登录关键路径 + 跑测试）。日期：2026-07-09。
> 性质：Opus 侧结论，GPT5.5 结论请追加到 §7。

---

## 0. 总体结论：**功能完整、服务端鉴权扎实；但有 9 个 MAJOR 须在内网上线前收口**

M2–M6 全部里程碑功能到位，工程质量总体高，**服务端 Keycloak JWT 校验是真验签(不是只解码)、写接口鉴权正确、解压防穿越、无 SQL 注入**。测试 `uv run pytest -q` → **168 passed, 2 skipped**（2 个 skip 为已披露的真实 devpi 网络用例）。

但**不建议把当前状态当作"内网生产可用基线"**：上传链路、前端登录令牌、流水线并发、供应链复验有 9 个 MAJOR 缺陷。其中 **M-A(市场登录要求未落实)** 直接与你本次提出的"使用 Skills 市场必须登录"冲突，需先决策。无 BLOCKER(功能不可用级)，但 MAJOR 密度偏高，集中在"对不可信输入的信任边界"。

---

## 直接回答你的两个问题

### Q1. 「让使用 Skills 市场必须是登录用户才可以」—— 当前**未满足**

现状是 M4 阶段**有意**把浏览设为匿名，登录只卡"写操作"：

| 能力 | 当前是否要登录 | 位置 |
| --- | --- | --- |
| 浏览列表 / 详情 / 搜索 / 排行榜 | ❌ 匿名 | `router.js:11-15` 无 guard；后端 `web/app.py` 读接口无 `Depends` |
| 上传 skill | ✅ 要 | `router.js:13` `requiresAuth` + 后端 `require_keycloak_user` |
| 评论 / 评分 | ✅ 要 | 后端 `require_keycloak_user` |

- **RBAC(来自 `E:\router\router` 的 .NET 权限中心)只控制前端菜单/路由可见性**(如是否显示"上传"入口)，且 `stores/auth.js:17-24` 在 RBAC 不可达时 `canUpload` **fail-open**。这是**有意设计**——RBAC 不是安全边界，真正边界是后端 Keycloak JWT 验签。此定位正确，保留。
- **要实现你的新要求(整个市场必须登录)**，需两处改动：
  1. 前端：`router.js` 改全局守卫，所有路由 `requiresAuth`(而非仅 `/upload`)；`main.js`/`authBootstrap.js` 启动即 `login-required`。
  2. 后端：所有读接口(`/api/skills`、`/search`、`/skills/{ns}/{name}`、`/leaderboard`、评论读)加 `Depends(require_keycloak_user)`——否则绕过 SPA 直接 `curl` 后端仍可匿名读(见 M-A)。
- 这是一次明确的**产品决策 + 小改动**。见下方 **M-A**。

### Q2. 「当前项目是基于 SkillsHub 改造的吗」—— **不是**

前端是**从 Vite 官方 Vue3 模板全新脚手架**起的，不是某个 "SkillsHub" 项目的分叉：
- `web/package.json` name 为 Vite 默认的 `"web"`、version `0.0.0`；`web/README.md` 是 create-vite 的原样模板 README。
- 全部业务代码围绕本项目自有后端 schema 手写(`App.vue`、`api.js`、store id `skillify-auth`、各 View)。
- **唯一的外部血缘**是 **RBAC token-bridge 模式**，改编自 `E:\Web\flow\web`(`bridge.ts`/`keycloak.ts`)，且在注释里明确标注(`rbacClient.js:5`、`stores/auth.js:3`、`keycloak.js:36`)。
- "skillsmp 模式"仅作为**概念参考**(agent 自拉取 UX)出现在 `docs/agent-self-pull.md`/PLAN，不是拷贝的代码库。

---

## 1. 逐里程碑验收核对

| 里程碑 | 状态 | 核实 |
| --- | --- | --- |
| M2 CI/webhook 打包 | ✅ 功能到位/⚠️ 并发 | `webhook/*` 验签(constant-time)+ `safe_extract` 复用；但 ingest upsert 非原子、work_dir 竞态(M-G) |
| M2 索引入库 | ✅/⚠️ | Postgres 索引写入；best-effort 但失败被吞(M-I)、缺复合索引(§3 MINOR) |
| M3 FastAPI 后端 | ✅ | 列表/详情/搜索/下载地址/安装命令 |
| M3 前端目录 | ✅ | 列表/详情(Markdown 渲染 `html:false` 安全)/搜索/复制 |
| M4 Keycloak 登录 | ✅ 服务端强/⚠️ 前端 | 后端真验签(见亮点)；前端令牌刷新回写缺失(M-E)、token 落 localStorage(M-F) |
| M4 上传+校验 | ⚠️ 有安全缺陷 | 校验器复用正确，但 name 路径穿越(M-B)、无归属校验(M-C)、无大小上限(M-D) |
| M5 评论+排行榜 | ✅/⚠️ | 无注入、评分 1-5、一人一评强制；但 `/events` 匿名可刷安装量(§3)、无分页 |
| M6 自拉取/上报/编排 | ✅ 作为预留 | 上报隐私良好；编排为 pass-through stub；自拉取端点缺 token(M-H，文档已诚实标注) |

---

## 2. 亮点（值得保留）

- **服务端 Keycloak 是真验签**：`web/auth.py:40-49` 走 JWKS 取签名公钥，`jwt.decode` 校验 RS256 签名 + `issuer` + `exp`/`iat`，**无"解码不验签"、无 dev bypass**。这是整套登录方案的地基，做对了。
- **写接口鉴权到位**：upload/comment/rating 均 `Depends(require_keycloak_user)`。
- **双解压均防穿越**：tar(`install/extract.py`)与 zip(`web/upload.py`)都拒符号链接 + 逃逸检测；`extract.py` 还补了无 `filter="data"` 旧 Python 的回退(**M0-M1 评审的 F5 已解决**)。
- **无 SQL 注入**：`comments.py`/`ratings.py`/`queries.py` 全程 SQLAlchemy 参数化。
- **RBAC 定位正确**：仅菜单可见性、fail-open、非安全边界，与后端 JWT 边界分工清晰；无硬编码 realm/client/secret，全走 env 占位。
- **上报隐私稳妥**：`telemetry.py` 默认关闭(需双开关)、不透明随机 machineId、无 PII、best-effort。

---

## 3. Findings（按严重度；MAJOR 须上线前收口）

> 无 BLOCKER。以下 MAJOR 均为"信任了不可信输入/未处理并发"，非功能不可用。

### M-A · 「市场必须登录」未落实【需产品决策 + 小改】
读接口(前端路由 + 后端)全部匿名，绕过 SPA 直连后端可匿名读。**修**：前端全局 guard + 后端读接口加 `require_keycloak_user`。见"直接回答 Q1"。

### M-B · 上传经 manifest `name` 路径穿越【安全，已复核确认】
`web/upload_service.py:45` → `common/skill_dir.py:14`：未校验的 `declared_name` 直接 `dest_root / declared_name` + `shutil.move`，**校验在 move 之后**。`name` 为绝对路径或含 `../` 时写出 `work_dir` 之外且不被清理。schema 最终会拒(pattern 不含 `/`.`)，但**文件系统副作用已发生**。**修**：rehome 前断言 `declared_name == Path(declared_name).name` 且匹配 name 正则；或先校验 manifest 再 rehome。

### M-C · 上传无命名空间/仓库归属校验【安全/越权】
`publish/publisher.py:110` `org = org_override or cfg.forgejo_org or result.namespace`，`repo = result.name`，上传流程不传 `org_override`。任一登录用户可对**他人 skill 发布新版本**或抢注任意名(旧版本被 `AlreadyPublishedError` 挡，新版本/新名不挡)。**修**：MVP 先按 Keycloak 身份派生/白名单绑定 namespace→owner，不信任上传 manifest 的 namespace。

### M-D · 上传体积无上限 → 内存耗尽 DoS【安全】
`web/app.py:245` `write_bytes(await file.read())` 整包读入内存，`safe_extract_zip` 无解压后总大小上限(zip bomb)。**修**：读前限 Content-Length + 解压时限累计解压大小。

### M-E · 前端刷新后的新 token 未回写【登录功能，实测会坏】
`web/src/lib/keycloak.js:62-72` `updateToken(30)` 成功后什么都不做，`api.js:16` 读的是 store/localStorage 里的**旧 token**。token 生命周期后所有写请求开始 401。**修**：刷新成功回调里 `auth.setSession(getKeycloak().token, ...)`。

### M-F · access token 持久化到 localStorage【安全，XSS 可窃】
`web/src/stores/auth.js:42` + `main.js` 用 `persistedstate` 把含 `token` 的 state 落 localStorage。keycloak-js 本可靠内存 + SSO cookie + `check-sso` 恢复。**修**：持久化路径排除 `token`(或整体不持久化，靠 `check-sso`)。

### M-G · 流水线并发不安全【M2 生产前必修】
`webhook/handler.py:76` work_dir 仅按 `owner__repo__version` 命名，Forgejo 重投递并发时互相 `rmtree`；`index/ingest.py` upsert 为 read-then-write,并发下第二个撞唯一约束报错。**修**：per-delivery 唯一临时目录 + `INSERT ... ON CONFLICT DO UPDATE`(或捕获 IntegrityError 转 update)。

### M-H · agent 自拉取端点无 token 认证【安全，文档已诚实标注】
`web/app.py` 的 `/api/skills/{ns}/{name}`、`/orchestration` 匿名，仅靠 Forgejo 仓库可见性。与"限内网 + token"要求半达标。**修**：加共享密钥/token 校验，或下调文档承诺。(作为"预留接口"可暂缓，但依赖它前必补。)

### M-I · 索引写入失败被静默吞掉【可观测性】
`publisher.py:83`、`handler.py` 把 `_index_release` 异常转成字符串塞进 `index_error` 仍返回 200，无日志/告警/重试。索引 DB 配错时不可见。**修**：至少 server 端记日志；考虑重试/DLQ。

### MINOR（择机加固，不阻塞）
- `auth.py:48` audience 仅在配置了才验 → 未设 `SKILLIFY_KEYCLOAK_AUDIENCE` 时接受同 realm 任意 client 的 token。建议生产**强制**(fail-closed)。
- `webhook/app.py` 未配 secret 时**跳过验签**且绑 `0.0.0.0` → fail-open。建议无 secret 拒绝启动。
- `verify.py` 验签 constant-time 正确但**无重放保护**(无 delivery-id 去重)——与 M-G 叠加会放大重复处理。
- `web/app.py` `/events` 匿名不限流 → 可用任意 machineId **刷高任意 skill 安装量**(喂给排行榜)。MVP 可接受,记为可刷。
- 列表/搜索无分页/limit；`search` 在 Python 侧对全量 `list_latest` 子串过滤(latent DoS/perf)。
- `web/app.py` CORS `allow_origins=["*"]`,且 `run()` 未读 env override → 通配符实际会上线。
- `queries.py` `list_latest()` 用 `max(id)` 近似"最新发布",重新入库旧版本会错位。建议按 `published_at` 排序。
- `models.py` 缺 `(namespace,name)` 复合索引与 `published_at` 索引;events/ratings 同。
- `auth.py:63` 报错回显 PyJWT 内部文本。建议返回通用"invalid token"。
- `resolver.resolve_release_artifact` 取第一个 `*.tar.gz`+第一个 `*.sha256`,不要求 basename 匹配(M0-M1 评审 C2,仍开放)。
- `keycloak.js:41` `redirectUri: window.location.href` 携全 URL,建议固定路由。PKCE `S256` 已正确开启。✓

### 供应链复验(M0-M1 评审 C1 仍开放,提级到 MAJOR 语境跟踪)
安装端 `installer.install_skill` checksum 通过后直接解压读 `skill.yaml`,**未复验**解出的 namespace/name/version 与请求/Release 是否一致,也未在安装端重跑 `validate_skill_dir`。真实 Forgejo 允许人工改 Release 资产时,内容/lock/Release 可三方不一致。**修**:安装端解压后调用 validator + 显式比对 identity,不符即失败清理。

---

## 4. 与 PLAN §0.1 登录决策的一致性

- Keycloak 前端直连 + 后端 JWT 验签 + RBAC 仅管菜单 + 全 env 占位 —— **与 PLAN §0.1 完全一致**,实现忠实。
- PLAN §0.1 记录的简化(发布仍走服务账号 token、上传者身份仅写入 Release notes/author 归属)在 `publisher.py` 注释中如实标注。但**这正是 M-C 越权的根因**:服务账号发布 + 无归属校验 = 任意登录用户可写任意仓库。建议把 M-C 列为 §0.1 的显式后续工作项。

---

## 5. 放行意见与建议顺序

**可进入下一阶段/联调,但当前不是内网生产基线。** 上线前(或接真实 Forgejo/Keycloak/devpi 前)按序处理:

1. **决策 M-A**:市场是否整体登录。若是,前端全局 guard + 后端读接口加鉴权。
2. **修上传安全三连 M-B/M-C/M-D**:name 穿越、归属校验、体积上限——上传对外开放前必修。
3. **修前端登录 M-E/M-F**:token 回写 + 移出 localStorage——否则登录体验/安全都有问题。
4. **修流水线 M-G/M-I**:原子 upsert + 唯一目录 + 索引失败记日志——接真实 Forgejo 前必修。
5. **补供应链复验(C1)+ resolver 精确匹配(C2)**。
6. **F6 真机验证**(M0-M1 评审):Docker compose / 真实 devpi / opencode 投影,仍须在真实内网各跑通一次。
7. MINOR 并入一次加固提交。

---

## 6. 已解决的历史项(M0-M1 评审)
- **F5**(tarfile filter 兼容旧 Python):已加回退分支 + 测试。✅
- F1(doctor agent 集合)/F2(update 依赖)/F4(菱形去重)/C1/C2:请 Sonnet 确认状态;从本次读到的 `resolver.py`/`installer.py` 看 **C1/C2 仍开放**(见 §3)。

---

## 7. GPT5.5/Codex 侧结论（联合复核，2026-07-10）

> 复核方式：按 `PLAN.md` / `TASKS.md` 的 M2-M6 验收项独立阅读当前代码，重点检查 Web/API 鉴权边界、上传链路、webhook 发布、索引写入、前端 Keycloak 会话、安装端供应链复验、M6 预留接口，并对照 Opus findings 做差异确认。

### 7.0 总体结论：**同意功能放行联调；不同意直接作为内网生产基线**

Codex 侧同意 Opus 的主判断：M2-M6 的功能面已经打通，服务端 Keycloak JWT 校验、写接口鉴权、tar/zip 安全解包、SQLAlchemy 参数化这些关键基础做得比较稳，适合进入真实环境联调。

但当前仍有多处上线前必须处理的信任边界问题，尤其是上传/发布归属、上传体积、前端 token 生命周期、webhook 并发、是否要求市场整体登录。若目标是“内网生产可用”，建议先做一次 M2-M6 hardening sprint，再谈上线。

### 7.1 与 Opus 结论的差异修正

#### D1 · M0-M1 的 C1/C2 当前代码已解决，不应继续列为开放项

Opus §3/§6 仍把“安装端供应链复验 C1”和“resolver 资产精确匹配 C2”列为开放；但以当前代码为准，这两项已经完成：

- `installer.install_skill` 已改为先解压到 staging 目录，并在落入真实安装目录前比较 `skill.yaml` 的 `namespace/name/version`，再调用 `validate_skill_dir` 复验。
- `resolve_release_artifact` 已按 `<namespace>-<name>-<version>` 精确匹配 tarball/checksum，并读取 `.artifact.json` 交叉校验 identity。
- 相关测试也已存在：`test_install_rejects_mislabeled_artifact_*`、`test_bad_reinstall_does_not_clobber_existing_good_install`、`test_resolver_*`。

**结论**：C1/C2 从本次 M2-M6 待修列表中移除；后续只需在真实 Forgejo 上做一次端到端验证。

#### D2 · M-B 应扩大为 shared helper 问题，影响 Web 上传和 webhook

Opus 说 M-B 是 Web 上传路径穿越，Codex 侧确认成立，并建议把根因定位到共享函数：

`common/skill_dir.py:rehome_to_declared_name` 直接用未校验的 `declared_name` 拼 `dest_root / declared_name` 再 `shutil.move`。它同时被：

- `web/upload_service.py` 的浏览器上传路径调用；
- `webhook/handler.py` 的 Forgejo archive 归位路径调用。

因此修复应放在 shared helper 或调用前的统一校验里，而不是只在 Web upload 上补一层。要求：`declared_name` 必须等于 basename，符合 manifest name 正则，且最终 resolved path 必须仍位于 `dest_root` 下。

### 7.2 认可并维持的 MAJOR Findings

- **M-A 市场整体登录未落实**：当前前端只有 `/upload` 有 `requiresAuth`，后端读接口也无 `Depends(require_keycloak_user)`。如果用户最终裁决“使用 Skills 市场必须登录”，这就是上线前第一优先级；前端和后端都要加，不能只靠 SPA guard。
- **M-B rehome 路径信任问题**：见 D2。属于对不可信 manifest 字段的文件系统副作用，建议优先修。
- **M-C 上传归属/越权**：后端服务账号发布，manifest namespace 决定 org/repo，任意登录用户可发任意 namespace 的新版本。MVP 需要至少做 namespace-owner 白名单或从 Keycloak claim 派生允许 namespace。
- **M-D 上传体积/zip bomb**：`upload_skill` 一次性 `await file.read()` 写入内存，zip 解压无累计大小/文件数上限。开放上传前必须加 Content-Length、流式/分块读取、解压累计上限。
- **M-E token 刷新后未回写 store**：`updateToken(30)` 成功后没有把新 token 写入 Pinia；`api.js` 继续读旧 token，写请求会在旧 token 过期后 401。
- **M-F access token 持久化到 localStorage**：当前 persistedstate 会持久化 `token`。建议排除 token，只持久化 username/RBAC 菜单等非敏感状态，token 交给 keycloak-js 内存态和 SSO cookie。
- **M-G webhook/索引并发不安全**：webhook work_dir 仍按 owner/repo/version 固定命名；索引 `upsert_release` 仍是 read-then-write，不是数据库级 upsert。真实 webhook 重投递/并发时仍可能互相删除目录或撞唯一约束。
- **M-H agent 自拉取端点缺 token**：文档诚实标注为预留接口，可以不阻塞联调，但依赖该通道前必须补应用层 token 或明确下调安全承诺。
- **M-I 索引失败可观测性不足**：index failure 只回传 `index_error`，缺服务端日志/重试/告警。作为 derived cache 可以不阻塞发布，但不能静默。

### 7.3 Codex 额外建议

#### G1 · 生产配置应 fail-closed，而不是“未配置即弱化”

当前有几处开发友好默认适合本地，但生产应明确拒绝启动或拒绝请求：

- `keycloak_audience` 未配置时不校验 audience；
- `webhook_secret` 未配置时 webhook 接受未签名 POST；
- CORS 固定 `allow_origins=["*"]`，`run()` 也没有读取部署环境中的 origin/host/port 配置。

建议新增一个 `SKILLIFY_ENV=production` 或显式 `strict_mode`，生产模式下强制要求 audience、webhook secret、CORS origin、Keycloak realm 等关键配置齐全。

#### G2 · `/events` 匿名可刷榜不只是 MINOR，取决于排行榜是否对用户可见

如果排行榜会成为首页/市场排序的一部分，匿名 `/events` 可以随意刷安装量，会影响社区信任。若只是内部观察指标，可先记为 MINOR；若用于排行曝光，建议提到 MAJOR：至少加机器级去重、限流、签名 token 或服务端按 lock/install 事件来源校验。

#### G3 · 搜索/list_latest 当前是 MVP 可用，不适合放大数据量

`list_latest()` 用 `max(id)` 近似最新，`search()` Python 侧全量过滤。MVP 小数据量可以接受；一旦进入真实市场，建议改为 DB 侧 latest 子查询 + ILIKE/全文索引 + limit/offset。

### 7.4 建议交付 Sonnet 的处理顺序

1. **先裁决 M-A**：市场是否整体登录。若“必须登录”，前端全路由 guard + 后端读接口 `require_keycloak_user` 一起做。
2. **修上传安全三连**：M-B shared helper 路径校验、M-C namespace 归属、M-D 上传/解压大小上限。
3. **修前端登录可靠性与安全**：M-E token refresh 回写，M-F token 移出 localStorage。
4. **修 M2 并发与可观测性**：M-G 唯一 work_dir + DB 原子 upsert，M-I 日志/重试策略。
5. **生产 fail-closed 配置**：audience、webhook secret、CORS、host/port/env 配置。
6. **M-H 自拉取 token**：若 M6 通道要给 agent 真用，补 token；若暂不用，在产品文档里继续标为 reserved。
7. **真实环境验证**：Docker compose、Forgejo webhook、Postgres index、Keycloak/RBAC、devpi index-url、opencode 目录投影逐项跑通。

### 7.5 联合裁决项

- **M-A**：市场是否整体必须登录？如果是，匿名 browse/search/detail/leaderboard 都要关闭。
- **M-C**：namespace 归属的 MVP 规则：Keycloak claim 派生 namespace，还是维护 namespace-owner 白名单？
- **M-H**：agent 自拉取 token 是上线前补，还是继续作为 reserved/stub 不对真实 agent 开放？
- **G2**：安装量排行榜是否参与排序/曝光？若参与，匿名 event 必须加固。

---

## 8. 技术栈决策：是否应改用 C# ASP.NET 6.0 开发（未来扩展视角）

> 背景：公司主力技术语言是 **C# ASP.NET 6.0**，而 Skillify 现状是**纯 Python（55 个 .py 文件：Typer CLI + FastAPI 后端 + 打包/安装/校验/索引全链路）+ Vue3 前端**，仅通过 token-bridge 复用外部 .NET 的 `Rbac.Api`/Keycloak。用户提出：从项目扩展角度，是否建议继续用 Python，还是主力语言 C# 对未来扩展更好？此节为 Opus 侧决策意见，交 GPT 联合评审。

### 8.0 结论先行

**不建议整体改写为 C# ASP.NET。建议保持"Python 核心 + Vue3 前端"，把语言选择限定在唯一真正可迁移的边界——Web 后端——上单独评估，且当前也倾向暂不迁移。** 原因一句话：**这个项目的领域本身就是 Python 的**（Claude Agent Skills、per-skill venv、uv、devpi、requirements.txt/pyproject 依赖隔离、agent/MCP/LLM 生态），改 C# 不能消除对 Python 运行时的依赖，只会把单栈系统变成"C# 壳 + 必须外挂 Python"的双栈系统，扩展更难而非更易。

### 8.1 关键：这不是"一个"语言决策，系统分三层，可迁移性完全不同

把 Skillify 当成一个整体来问"Python 还是 C#"会得出错误答案。它其实是三层，各层的迁移代价与收益差一个数量级：

| 层 | 现状 | 是否可迁 C# | 迁了会怎样 |
| --- | --- | --- | --- |
| **A. CLI / 打包 / 安装 / skill 运行时**（`skillctl`、venv、devpi、agent 投影） | Python + uv | **不应迁**。这是项目的护城河，且天然 Python | 即使用 C# 重写 CLI，创建 per-skill venv、装 `requirements.txt`、跑 skill 脚本**仍必须 shell out 到 Python/uv**。等于既维护 C# 又维护 Python，零收益 |
| **B. Web 后端**（FastAPI：列表/搜索/上传/评论/排行榜/JWT 校验） | FastAPI | **唯一可正当迁移的层**。本质是 Postgres+Forgejo+Keycloak 之上的 CRUD/聚合服务，ASP.NET 6 完全胜任 | 能与公司现有 .NET Keycloak/RBAC 模式同栈、由 .NET 团队维护。但**已用 FastAPI 建好、测过、评审过**，迁移是重写沉没成本 |
| **C. 前端**（Vue3） | Vue3 | 与后端语言无关 | 无论后端是什么语言都不变，无需讨论 |

> PLAN.md §7 本身已把 CLI 的备选记为 **"Python(Typer) 还是 Go"**——注意备选是 Go（单二进制分发诉求），从来不是 C#。这说明 A 层的语言选择维度是"分发/性能"，不是"对齐公司语言"，用 C# 替 A 层是问错了问题。

### 8.2 核心事实：Skills 生态天然是 Python，这是不可回避的领域约束

- **依赖隔离模型本身就是 Python venv**：Skillify 最核心的价值（per-skill 依赖隔离、内网 devpi 镜像、uv 装包）是 Python 原生能力。C# 侧没有等价物，只能调用 Python。
- **被服务的 agent 与 AI/LLM 生态是 Python/TypeScript 一等公民**：Claude Code / OpenCode / Codex / Aider、MCP server、agent SDK、编排框架（M6 的 orchestration 扩展方向）——绝大多数是 Python/TS 优先，C# 是二等公民。**未来扩展的每一个方向（新 agent 适配、MCP 通道、编排引擎）都会把项目往 Python/TS 拉，而不是往 C# 拉。**
- **skill 内容 = Python 脚本**：作者上传的 skill 携带 `requirements.txt`/`pyproject.toml`，平台要校验、打包、装它们的依赖——用 Python 工具链处理 Python 制品是最短路径。

**因此对"Python 对未来扩展好不好"的直接回答：对本项目——好。** 扩展向量（agent/MCP/编排/LLM 工具）全是 Python/TS 优先域；改 C# 会让"往 AI/agent 方向扩展"更难。C# 唯一帮到的是"对齐内部 .NET 团队与基础设施"，那是真实的组织诉求，但应在 **B 层这个薄且可替换的边界**上解决，而不是动核心。

### 8.3 平衡地看：C# 真正赢在哪、Python 真正赢在哪

不偏袒任何一方，各自的真实优势：

**C# ASP.NET 6.0 真正的赢点（都是组织/运维维度，不是技术领域维度）**
- **团队可维护性**：公司开发者懂 C#，长期由内部团队维护 B 层后端时，同栈降低维护门槛。这是最强的一条。
- **与现有内部系统同栈**：已有 `Rbac.Api`（.NET 菜单级权限中心）、Keycloak 的 .NET 接入范式、以及围绕 .NET 调优的部署/监控/CI 流水线。B 层用 ASP.NET 可直接复用这套企业基建与鉴权中间件。
- **静态类型与企业级工具链成熟度**：对纯 CRUD 后端，编译期类型与 EF Core/中间件生态是加分项（不过 FastAPI+Pydantic+SQLAlchemy 在这一层已足够，差距不大）。

**Python 真正的赢点（都是领域/成本维度）**
- **领域原生**：venv/devpi/uv/skill 制品处理，见 §8.2，不可替代。
- **已建成且过评审**：M0–M6 全部完成、168 测试全绿、经 Opus+GPT 两轮评审。重写是纯沉没成本，无功能增量。
- **扩展方向对口**：agent/MCP/编排/LLM 生态 Python 优先。
- **单栈简单**：现状后端与 CLI 同栈（`publisher.py` 被 CLI 与 webhook 共享，避免漂移，见 §1）；A/B 拆到两种语言会引入跨语言的模型/校验重复。

### 8.4 迁移成本 vs 收益（针对"整体改 C#"这一激进选项）

- **成本**：A 层无法真正迁（仍需外挂 Python）→ 得到双栈；B 层是重写已过评审的代码；两处对 `skill.yaml`/校验规则/打包契约的实现要么重复、要么 B 层反过来调 A 层的 Python——复杂度净增。
- **收益**：仅 B 层的"团队同栈 + 复用 .NET 基建"，且该收益只在"维护团队是纯 .NET、无法维护 Python"时才成立。
- **判断**：整体改 C# 是**负收益**。已有的跨语言协作证据：本仓库 Python 后端**已经**通过 token-bridge 干净地调用了外部 .NET `Rbac.Api`（`web/src/lib/rbacClient.js`）——证明"Python 核心 + 复用 .NET 基建"的混合架构已经跑通，无需为了同栈而重写。

### 8.5 推荐路线（供裁决）

1. **A 层（CLI/打包/安装/运行时）：坚定保持 Python。** 这是护城河且领域原生，改任何语言都要外挂 Python。若未来有单二进制分发诉求，备选是 **Go**（PLAN §7 已记），仍不是 C#。
2. **C 层（前端）：保持 Vue3。** 与后端语言无关。
3. **B 层（Web 后端）：当前建议保持 FastAPI，不迁。** 它已建好/测过/评审过，且与 A 层同栈共享打包发布逻辑。**仅当**满足"长期维护团队为纯 .NET 且明确无法维护 Python 服务"时，才把 B 层——且只把 B 层——迁到 ASP.NET 6：它是纯 CRUD/聚合 + Keycloak JWT 校验，是整个系统里唯一薄到可以低风险替换的边界，迁移时 A 层继续用 Python 提供打包/安装能力，B 层通过 REST/子进程调用即可。
4. **无论是否迁 B 层，都优先解决 §3 的 9 个 MAJOR**——语言决策不改变那些"信任边界"缺陷，别让语言问题拖住上线收口。

> 一句话给决策者：**"用不用 Python"不该是全局开关。核心必须是 Python，前端是 Vue3，只有那层薄薄的 Web 后端才谈得上换 C#，而它现在也已经建好了。为"公司主力语言"去重写一个已过评审的 AI/agent 领域系统，方向与项目的扩展趋势相反。**

### 8.6 留给 GPT 联合评审的开放问题（技术栈）

- Skillify Web 后端（B 层）的**长期维护团队**到底是谁？若是纯 .NET 团队且拒绝维护 Python 服务，则 B 层迁 ASP.NET 6 的组织理由成立——这是**唯一**能翻转"保持 FastAPI"结论的因素，需用户明确。
- 若迁 B 层：A 层（Python 打包/安装）与 B 层（C#）之间的契约走 **REST 调 `skillctl`** 还是 **C# 直接 shell out 到 Python**？建议前者（进程边界清晰）。
- 是否存在"整个内网只允许 .NET 技术栈"的硬性合规/运维约束？若有，需重新评估 A 层被迫外挂 Python 的可行性（内网 Python/uv/devpi 是否被允许部署）——这会反过来影响整个项目可行性，应在联合评审中先确认。

### 8.7 Codex 对技术栈决策的复核意见

Codex 侧同意 Opus §8 的结论：**不建议整体改写为 C# ASP.NET 6.0**。原因不是 Python “更好看”，而是本项目核心能力天然依赖 Python 工具链：`uv`、per-skill venv、`requirements.txt`/`pyproject.toml`、devpi、Claude Agent Skills 目录与脚本生态。即使 Web 后端改 C#，A 层仍必须保留 Python，整体改写会变成“双栈 + 进程编排”，复杂度增加。

更合理的边界是：

- **CLI/打包/安装/依赖隔离/agent 适配：保持 Python。** 这是核心域，不建议迁。
- **前端：保持 Vue3。** 与后端语言无关。
- **Web 后端：短期保持 FastAPI。** 只有当长期维护团队明确是纯 .NET 且无法维护 Python 服务时，才单独评估把 Web 后端迁到 ASP.NET；迁移时也应通过 REST/子进程调用 Python 核心能力，而不是重写打包安装链路。

因此语言问题不应阻塞当前上线加固。优先级仍是 §7 的 MAJOR findings：认证边界、上传安全、并发、可观测性和真实环境验证。

---

## 9. 复评：M-A~M-H 加固验收（Opus 4.8，2026-07-10）

> 触发：Sonnet 5 完成 M-A~M-H 修复并报"195 tests passing（从 168 增加），前端构建干净"。
> 复评方式：**不采信摘要**——Opus 亲自 `uv run pytest -q` 复跑 + 3 个并行子评审 agent 逐文件对抗性核验每条修复的 file:line 证据（不是只看测试绿）。

### 9.0 复评结论：**8 条修复全部 VERIFIED（真实落地，非仅测试通过）；M-I 按裁决仍开放。可进入真机联调收尾。**

- 测试复跑：`uv run pytest -q` → **195 passed, 2 skipped**（83s），与 Sonnet 报告一致；2 个 skip 仍是已披露的真实 devpi 网络用例。
- 逐条对抗性核验（每条都读了实际代码、确认"校验在副作用之前/鉴权真的挂上/upsert 真的原子"，而非仅看命名）：全部通过。原 §3 的 9 个 MAJOR 中，**M-A~M-H 8 条已收口**，**M-I（索引失败可观测性）按 §7 裁决明确留作后续**——本轮确认代码里仍无 server 端日志（`publisher.py` 无 `import logging`），与"暂不管"的裁决一致，非回归。

### 9.1 逐条核验结果

| 项 | 结论 | 关键证据（file:line） |
| --- | --- | --- |
| **M-A** 市场整体登录 | ✅ VERIFIED | 后端 8 个读接口全部 `Depends(require_keycloak_user)`（`web/app.py` list:71 / search:83 / detail:93 / install:106 / orchestration:115 / comments-read:132 / leaderboard:176）；`require_keycloak_user`（`auth.py:54-65`）fail-closed（缺/坏 token→401，Keycloak 未配→503 不放行）。前端 `router.js:34` 全局 `beforeEach` + `bootstrapSession()` 走 `check-sso` **实时**会话校验（非读持久化 token）。`api.js:20-21` 读接口也挂 Authorization 头 |
| **M-B** 上传 name 路径穿越 | ✅ VERIFIED | `common/skill_dir.py:27-43`：`is_valid_segment` 正则校验 + resolved 路径逃逸检查**均在 `shutil.move` 之前**；upload 与 webhook 两条路径共用同一函数（`upload_service.py:65`、`handler.py:121`），无漂移 |
| **M-C** namespace 归属 | ✅ VERIFIED | `index/ownership.py:28-51` 按 Keycloak `preferred_username` first-publish-wins，靠 DB 唯一约束 + `IntegrityError` 重查做原子；`upload_service.py:73-74` index_db 未配 → 抛错 → `app.py:285` 映 503 **fail-closed**。跨用户抢注/他人 namespace 发版均被测试挡（403） |
| **M-D** 上传/zip 体积上限 | ✅ VERIFIED | `app.py:256-270` 1MiB 分块流式落盘 + `max_upload_bytes`（默认 20MiB）超限 413；`web/upload.py:30-58` 解压前查文件数（5000）+ 解压总大小（100MiB）上限 |
| **M-E** token 刷新回写 | ✅ VERIFIED | `keycloak.js:73` `updateToken` 成功 → `onRefreshed(token)`，`authBootstrap.js:34/48` 接到 `auth.setSession(...)` 写回 Pinia |
| **M-F** token 不落 localStorage | ✅ VERIFIED | `stores/auth.js:47` `persist.paths: ['username','rbacInfo','menus']` 明确不含 `token`；恢复靠 `check-sso` |
| **M-G** 流水线并发安全 | ✅ VERIFIED | `handler.py:95` work_dir 带 `uuid4().hex` 每投递唯一 + `_PATH_SAFE_RE` 对 owner/repo/version 路径校验（line 30/48-50，在建目录前）；`index/ingest.py:53-75` `begin_nested()`（SAVEPOINT）insert→`IntegrityError` 回退 update，真原子 upsert |
| **M-H** 自拉取端点 | ✅ VERIFIED（作为 reserved） | 随 M-A 继承鉴权：`/api/skills/{ns}/{name}`、`/orchestration` 已挂 `require_keycloak_user`；`docs/agent-self-pull.md:44-56` 已更新说明继承 Keycloak 要求、专用 token 仍是明确留白 |

### 9.2 复评新发现（子评审 agent 顺带查出，供 GPT 联合评审 / 记入后续）

均**非本轮 8 条修复的缺陷**，是收口时应知会的边角项：

1. **`POST /api/skills/{ns}/{name}/events` 仍匿名**（`app.py:218-219`，有注释说明 CLI 无浏览器会话）。它是**写**接口，不在 M-A"读接口整体登录"范围内，故不算 M-A 未达标；但它正是原 §3 MINOR 与 §7 G2 说的"匿名可刷安装量/注入 telemetry"入口——**若排行榜参与市场排序/曝光，此项应从 MINOR 升级处理**（机器级去重/限流/来源校验）。M-A 关了读侧匿名，但这个写侧匿名面仍在。
2. **前端 guard 在 Keycloak 未配置时 fail-open**（`router.js:35` 直接放行）——对 dev 合理，但生产若误删 `VITE_KEYCLOAK_REALM_URL` 会静默关掉前端门禁；真正边界仍是后端 JWT（后端在此场景返回 503，不会裸奔），可接受，但建议纳入 §7 G1 的"生产 strict_mode 强校验配置齐全"。
3. **M-C 归属键是 namespace 整体**（非 namespace/name）——首个上传者拥有该 namespace 下所有 name，是 `models.py:76-82` 文档化的 first-publish-wins 语义；webhook 路径不走此表，改用 Forgejo 仓库 owner（`org_override`，独立且更强）。属设计选择，请在联合评审确认符合预期。
4. **M-I 仍开放（符合裁决）**：索引写失败只塞进 HTTP 响应体 `indexError`，server 端无日志/告警。接真实 Postgres 前建议至少补日志。

### 9.3 放行意见

**M-A~M-H 加固确认到位，可从"评审加固"阶段进入真机联调收尾。** 剩余按 §7.4 顺序推进：M-I 可观测性、生产 fail-closed 配置（G1：audience/webhook secret/CORS/env）、`/events` 匿名面（G2，若排行榜曝光则必修）、以及 §5/§6 的真实环境验证（Docker compose / Forgejo webhook / Postgres index / Keycloak-RBAC / devpi index-url / opencode 投影）逐项跑通。语言决策（§8）与本轮加固正交，不阻塞。

> **GPT5.5 复评结论请追加于此**：如对 9.1 任一条的 VERIFIED 判定或 9.2 的四项有分歧，并列记录交用户裁决。
