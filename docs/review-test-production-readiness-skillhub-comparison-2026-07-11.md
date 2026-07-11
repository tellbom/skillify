# Skillify 测试与上线就绪度评审及 Skillhub 功能对比

- 评审日期：2026-07-11
- 评审对象：`E:\skillify` 当前 `main`，对照 `E:\skillhub` 当前 `main`
- 评审重点：功能完整性、产品特性、真实业务闭环、部署可用性和可借鉴能力
- 适用范围：当前内网使用阶段，暂不把 API 防护、外网攻击面和内容安全扫描作为上线阻断条件
- 本文不记录任何测试账号、令牌、数据库或服务器密码。

## 1. 结论

### 1.1 测试环境：GO

Skillify 已具备进入测试环境进行 MVP 验收和前后端共同联调的条件。当前已经实现：

- Skill 初始化、校验、打包、发布、安装和更新。
- Forgejo 仓库与 Release 制品管理。
- PostgreSQL 索引、搜索、详情和版本读取。
- Web ZIP 上传。
- 评论、评分、安装/运行排行榜。
- Keycloak 登录和 Rbac.Api 动态菜单。
- Claude 等 Agent 目录投影及 Python 独立 venv。

本次本地门禁结果：

| 门禁 | 结果 |
| --- | --- |
| `uv run pytest -q` | 196 passed，2 skipped，2 warnings |
| `npm test -- --run` | 5 个测试文件、28 个测试全部通过 |
| `npm run build` | 通过，有大分块警告 |
| `npx vue-tsc --noEmit` | 失败，21 个 TypeScript/Vue 类型错误 |
| FastAPI `/openapi.json` | HTTP 200 |
| Docker/Compose 实机验收 | 未执行；当前机器没有 Docker 命令 |

类型错误不阻止当前测试环境启动，但应在测试周期内处理，避免后续 RBAC 管理页面扩展时积累更多类型问题。

### 1.2 内网正式使用：测试闭环通过后可以分阶段上线

在暂不考虑 API 额外防护和内容安全扫描的前提下，Skillify 不需要等待 Skillhub 全部功能完成后才上线。建议采用“小范围试用 -> 部门级推广 -> 全量内网开放”的方式。

首批用户上线前需要完成的核心条件只有四类：

1. 提供完整的前端、`skillify-web`、webhook、Forgejo、PostgreSQL 和 devpi 部署入口。
2. 在真实环境跑通上传、发布、索引、浏览、安装、更新和评论/评分闭环。
3. 解决发布中断后的重试与索引重建，避免用户看到半发布状态。
4. 明确数据备份、数据库升级和版本回退方式，避免测试数据迁入正式环境后无法演进。

功能测试全部通过并完成上述四项后，可以先向内网种子用户开放。Skill 生命周期、收藏订阅、版本对比、更强搜索等能力可以按优先级迭代，不必全部阻塞首版。

## 2. 当前功能完成度

| 功能域 | 当前状态 | 测试阶段判断 |
| --- | --- | --- |
| Skill manifest 与目录校验 | 已实现 | 可测 |
| CLI init/validate/publish/install/update/doctor | 已实现并有测试 | 可测 |
| Forgejo Release 发布 | 已实现 | 需要真实 Forgejo 验证 |
| Git tag webhook 自动发布 | 已实现 | 需要真实 Forgejo 验证 |
| Web ZIP 上传 | 已实现 | 需要前后端真实闭环 |
| Skill 列表、搜索、详情 | 已实现基础版本 | 可测，功能仍可扩展 |
| 多版本存储 | 索引可记录多个版本 | 缺少完整版本管理界面 |
| 评论 | 已实现平铺评论 | 缺少删除、回复和管理能力 |
| 评分 | 已实现 1-5 分及重复评分更新 | 可测 |
| 排行榜 | 已实现安装量、评分、最近发布 | 统计规则仍较基础 |
| Agent 安装投影 | 已实现 | 需在真实用户机器验证 |
| Python 依赖隔离 | 每 Skill 独立 venv | 需验证复杂依赖和离线源 |
| 登录与动态菜单 | 已实现 Keycloak + Rbac.Api 桥接 | 已有联调记录，需浏览器回归 |
| 容器化交付 | 只有 webhook 镜像和开发 Compose | 尚不完整 |
| 数据库升级 | 使用 `create_all` | 尚无版本化 migration |

## 3. 上线前功能与可靠性问题

### P0-1：缺少完整产品部署入口

证据：

- `Dockerfile:14` 只启动 `skillify-webhook`。
- `infra/docker-compose.yml:4-74` 只包含 PostgreSQL、Forgejo、devpi 和 webhook。
- Compose 没有 `skillify-web` 和前端静态站点服务。
- `infra/README.md:71-82` 说明当前配置尚未经过真实 Docker 端到端验收。

影响：当前仓库不能通过一套部署命令直接得到用户可访问的完整 Skillify。

建议：增加前端构建/静态服务、`skillify-web` 服务和统一反向代理配置。测试环境应尽量使用未来正式环境相同的镜像和启动方式。

### P0-2：发布过程缺少可恢复性

证据：

- `src/skillify/web/upload_service.py:75-83` 先写 namespace ownership，再调用 Forgejo 发布。
- `src/skillify/publish/publisher.py:115-130` 依次创建仓库、Release、上传三个资产，最后写索引。
- 索引写入失败只返回 `index_error`，没有自动重试和全量重建命令。

影响：中途失败可能留下空仓库、资产不完整的 Release、已经占用的 namespace 或 Forgejo 已发布但页面没有索引的数据。用户再次上传同版本时也可能无法自然恢复。

建议：第一阶段不一定需要引入消息队列，可先实现：

1. 发布步骤状态记录。
2. 同版本幂等重试。
3. 检查并补传缺失 Release asset。
4. 从 Forgejo Release 全量或按仓库重建 `skill_index`。
5. 发布失败时释放首次 namespace 占用，或提供管理员修复命令。

### P0-3：真实发布与安装闭环仍未验收

自动化测试大量使用 fake Forgejo、fake Keycloak 和临时数据库。`infra/README.md:71-82` 也明确说明 Docker 链路尚未实机验证。

正式试用前至少要完成一次真实闭环：

`Web/CLI 上传 -> Forgejo repo/Release -> PostgreSQL index -> Web 搜索/详情 -> skillctl install -> venv/Agent 目录 -> update`

还要覆盖 Git tag webhook 发布路径，确认 Web 上传与 Git 发布两种入口最终产生一致的 Release 结构和索引数据。

### P1-1：数据库缺少版本化升级

`src/skillify/index/db.py:17-22` 使用 `Base.metadata.create_all`。该方式适合初始建表，但后续新增 Skill 状态、收藏、订阅、回复、版本字段时，不能可靠完成已有数据升级。

建议引入 Alembic，把现有五张业务表作为基线 migration。无论继续使用 PostgreSQL，还是以后迁移 MySQL，都应让 migration 成为业务表结构的唯一升级入口。

### P1-2：Web 上传没有形成 Git 源码历史

当前 Web ZIP 上传执行 `ensure_org_repo + create_release + upload assets`，不会把解压后的提示词和脚本 commit 到 Forgejo Git 历史。结果是：

- Release 制品有版本且不可覆盖。
- Web 上传内容可以安装和下载。
- Forgejo 仓库源码页可能为空，无法使用 commit diff、在线浏览和分支协作。

这不是现有安装功能的错误，但需要产品决策：

- 若 Forgejo 主要承担“制品仓库”，保持 Release-only 即可。
- 若 Forgejo 还要承担“提示词和脚本源码版本管理”，Web 上传后应创建 commit/tag，再生成 Release。

建议正式功能定位采用第二种方式，这样用户通过 Web 和 Git 发布的 Skill 都能在 Forgejo 查看源码历史和版本差异。

### P1-3：版本管理只有数据基础，缺少用户功能

Skillify 已能保存多个 Release 和多个 `skill_index` 版本，但 Web 主要展示最新版本，尚缺少：

- 版本列表和发布时间线。
- 两个版本的 manifest、提示词和脚本差异对比。
- 指定版本安装。
- 旧版本撤回或标记不可推荐。
- 最新稳定版本与历史版本的清晰区分。
- 发布说明和变更记录展示。

这是最值得从 Skillhub 借鉴的功能域之一。可以继续用 Forgejo Release 作为底层，不需要复制 Skillhub 的存储实现。

### P1-4：搜索与发现能力只覆盖基础场景

当前搜索主要按名称和描述匹配，列表返回结构也比较轻量。用户量和 Skill 数量上升后，建议增加：

- 分页。
- namespace、标签、作者筛选。
- 最近发布、安装量、评分等排序。
- Agent 类型、语言、依赖环境等能力筛选。
- 热门标签和分类入口。
- 搜索结果中直接显示版本、评分、安装量和更新时间。

### P1-5：个人工作台与管理入口不足

当前系统偏向市场浏览和上传，缺少用户持续维护 Skill 的工作区。建议增加：

- 我的 Skill。
- 我的 namespace。
- 我上传的版本及发布结果。
- 失败发布重试。
- 我安装/收藏/评分过的 Skill。
- Skill 使用统计和版本采用情况。

Skillhub 的 “My Skills / My Namespaces / Settings” 可以作为信息架构参考，但 Skillify 首版不必复制完整团队治理。

### P2-1：社区互动仍是基础版本

评论、评分和排行榜已经可用，后续可依次补充：

1. 评论删除和回复。
2. 收藏/Star。
3. Skill 更新订阅。
4. 新版本通知。
5. 评论和评分的个人历史。
6. 排行榜时间范围，例如本周、本月、全部。

### P2-2：前端工程门禁与加载体积

当前 `vue-tsc` 有 21 个类型错误，Vite 构建存在多个超过 500 kB 的 chunk，主 chunk 约 1 MB。建议先清理类型错误，再按实际展示语言按需加载 Shiki 语法包。两项不阻止当前测试，但会影响后续功能开发和内网低带宽体验。

## 4. Forgejo 与业务数据库的数据边界

| 数据 | 当前落点 | 作用 |
| --- | --- | --- |
| Skill 发布包、checksum、artifact manifest | Forgejo Release assets | 安装和下载的权威制品 |
| Skill Git 源码 | Git/webhook 发布路径存在 | 提示词和脚本源码版本管理 |
| Web ZIP 上传源码 | 当前未 commit | 只有 Release 制品，没有 commit 历史 |
| Skill 检索元数据 | Skillify 业务库 `skill_index` | 搜索、详情和版本索引 |
| 评论 | Skillify 业务库 `skill_comments` | 社区互动数据 |
| 评分 | Skillify 业务库 `skill_ratings` | 评分和排行榜数据 |
| 安装/运行事件 | Skillify 业务库 `skill_events` | 使用统计和排行榜数据 |
| namespace 所有权 | Skillify 业务库 `skill_namespace_owners` | Web 上传归属关系 |

Forgejo 与 Skillify 可以共用一台 PostgreSQL 实例，但应继续使用各自独立数据库。评论、排行榜等业务表迁移到 MySQL不会改变 Skill 的发布和安装核心能力；但新增功能越多，迁移成本越高，因此应尽早确定正式业务数据库并引入 migration。

## 5. 与 Skillhub 的功能差异

Skillhub 当前仓库包含 43 个 Flyway migration、43 个 Playwright E2E spec 和 15 个 GitHub Actions workflow。它是较完整的企业 Skill 注册中心；Skillify 则以 Forgejo 作为源码和制品基础设施，架构更轻。

| 功能域 | Skillify 当前能力 | Skillhub 可参考能力 | 借鉴优先级 |
| --- | --- | --- | --- |
| Skill 发布 | CLI、Web ZIP、Git webhook、Forgejo Release | 平台上传、版本状态和统一发布流程 | 高：统一两种入口的结果 |
| 源码版本 | Git 路径有 commit，Web 上传仅 Release | 文件浏览、版本文件和版本对比 | 高：Web 上传补 commit，增加 diff |
| 生命周期 | 发布后直接可见，版本不可覆盖 | Draft、Pending Review、Published、Rejected、Yanked | 中：先实现 Published/Yanked，再按需要加审核 |
| 版本体验 | 后端保存多版本，前端偏最新版本 | 版本列表、latest published、owner preview、版本比较 | 高 |
| 搜索发现 | 名称/描述基础搜索和三个排行榜 | 多条件筛选、分页、可见性、流行度和时间排序 | 高 |
| 个人工作台 | 上传页和市场功能为主 | My Skills、My Namespaces、个人设置 | 高 |
| namespace | 首次上传者占用 | 成员、Owner/Admin/Member、namespace 页面 | 中：先补 namespace 详情和 Skill 聚合 |
| 社区功能 | 评论、评分、排行榜 | Star、订阅、通知、举报、评分 | 中：Star 和订阅最值得先做 |
| 使用统计 | 匿名 install/run 事件 | 下载量、评分、订阅和统计字段 | 中：增加时间维度和去重口径 |
| CLI | init/validate/publish/install/update/doctor | 登录、token、多平台兼容发布 | 中：优先优化安装和版本选择体验 |
| 依赖安装 | devpi + 每 Skill venv | 平台制品下载与 CLI 安装 | 保持 Skillify 现有特色 |
| 数据升级 | `create_all` | Flyway migration | 高：用 Alembic 借鉴原则 |
| 部署 | 开发 Compose、webhook 镜像 | release Compose、staging、K8s、监控 | 高：先补完整 Compose；K8s 后置 |
| 自动化测试 | Python/Vitest 较完整 | Playwright、CLI、staging、镜像流水线 | 高：增加核心闭环 E2E |
| 安全扫描与治理 | 本阶段不作为核心目标 | Scanner、审计、举报、审核 | 低：作为未来外网化/规模化能力 |

## 6. 最值得借鉴的产品特性

### 第一优先级：直接改善 Skill 管理和使用

1. **版本中心**：版本列表、变更说明、文件浏览、版本 diff、指定版本安装、撤回旧版本。
2. **我的 Skill**：查看自己上传的 Skill、版本、发布状态、失败原因和使用数据。
3. **搜索与筛选**：分页、标签、namespace、作者、Agent、评分、安装量和更新时间排序。
4. **Web 上传进入 Git 历史**：确保提示词和脚本可以在线查看、比较和回溯。
5. **索引重建与发布重试**：让 Forgejo 与 Skillify 页面数据可恢复。
6. **完整部署包**：一套 Compose 拉起用户真正使用的前后端和基础设施。

### 第二优先级：形成内部 Skill 社区

1. 收藏/Star。
2. Skill 更新订阅和站内通知。
3. namespace 聚合页和成员协作。
4. 评论回复、作者回复标记和评论管理。
5. 本周/本月/全部排行榜。
6. 安装历史与常用 Skill 快捷入口。

### 第三优先级：规模扩大后再建设

1. 完整审核工作流和推广流程。
2. 举报、审计和安全扫描。
3. Redis、消息队列、S3/MinIO 存储抽象。
4. 高可用和 Kubernetes。
5. 语义搜索和推荐系统。

## 7. 不建议直接照搬 Skillhub 的部分

- 不需要改写成 Java/React，当前 Python/FastAPI/Vue 足以支撑内网目标。
- 不需要立即替换 Forgejo。Forgejo 的 Git、Release、权限和版本能力正是 Skillify 的核心差异。
- 不需要一开始就引入 Redis、S3、消息队列和 Kubernetes。
- 不需要在首版实现完整审核、推广、举报、公开注册和复杂团队角色。
- 不应把 Skillify 评论、排行榜等业务表写入 Forgejo 自有 schema，两套系统保持数据所有权边界更利于升级。

## 8. 测试环境验收清单

### 8.1 完整业务闭环

- Keycloak 登录 -> Rbac.Api 菜单 -> Skill 列表/搜索/详情。
- Web 上传 ZIP -> Forgejo repo/Release/三个资产 -> `skill_index` -> 页面可见。
- Git push tag -> webhook -> Release -> 索引。
- `skillctl install namespace/name` -> checksum/identity 校验 -> venv -> Agent 目录。
- 发布新版本 -> 页面显示最新版本 -> `skillctl update` 更新。
- 评论、重复评分更新、三个排行榜维度。
- 重新启动服务后，Forgejo、业务库和 devpi 数据保持完整。

### 8.2 功能异常与恢复

- 重复发布同一版本时给出明确提示。
- Forgejo 在创建 Release 或上传资产中断后，可以继续或重新发布。
- Forgejo 已有 Release、业务库缺少索引时，可以重建索引。
- 并发上传同一 namespace 或同一版本时结果一致。
- devpi 不可用时，纯提示词 Skill 与包含 Python 依赖的 Skill 分别给出正确结果。
- 安装包身份、版本或 checksum 不匹配时拒绝安装并保留原版本。
- 大包、多文件和复杂依赖 Skill 有可理解的进度与错误信息。

### 8.3 前端体验

- 目标浏览器完成登录、动态菜单、上传、列表、详情、评论、评分和排行榜 E2E。
- 空数据、加载中、失败、无搜索结果和无历史版本状态完整。
- 上传和安装错误能显示后端返回的具体原因。
- 中文文案完整，长 Skill 名称、长标签和长评论不破坏布局。
- 修复 21 个 `vue-tsc` 错误并把类型检查加入 CI。

## 9. 内网上线门槛

满足以下条件即可进入种子用户试用：

1. 完整部署拓扑可以在目标 Linux 主机重复安装和启动。
2. 第 8 节核心闭环全部通过，并保留测试记录。
3. 发布中断可重试，Forgejo 索引可重建。
4. PostgreSQL、Forgejo 和 devpi 数据完成一次备份与恢复验证。
5. 数据库具备 Alembic 基线和明确的升级步骤。
6. 前端类型检查、后端测试、前端测试、构建和核心 E2E 全部通过。
7. 有版本发布、回退、数据恢复和用户问题处理说明。

试用阶段建议先限制用户数量和 namespace 数量，重点观察上传成功率、安装成功率、索引一致性、常见搜索方式和用户最需要的管理功能。根据真实使用数据决定第二批功能，而不是预先复制 Skillhub 的全部模块。

## 10. 建议实施顺序

### 阶段 A：完成测试环境闭环

补前后端部署服务；修复类型错误；跑通真实 Forgejo/PostgreSQL/devpi；验证 Web、Git、CLI 三条路径。

### 阶段 B：达到内网可用

增加 Alembic、发布重试、索引重建、完整 E2E、备份恢复和基础使用文档，然后开放种子用户。

### 阶段 C：增强核心产品体验

优先实现版本中心、我的 Skill、Web 上传 Git commit、搜索筛选、Star 和订阅通知。

### 阶段 D：按规模扩展

根据实际需要增加 namespace 协作、审核下架、评论治理、安全扫描、消息队列、对象存储和高可用部署。

## 11. 供 Claude 联合评审的问题

1. 是否同意当前系统已经可以进入测试环境，并在闭环通过后进行小范围内网上线？
2. Web ZIP 上传是否应默认 commit 到 Forgejo，从而让 Release 制品与 Git 源码版本保持一致？
3. 版本中心首版应包含哪些能力：版本列表、diff、指定版本安装、yank、变更说明？
4. Forgejo Release 到 `skill_index` 的重建应该按仓库触发，还是提供全量扫描命令？
5. 当前是否需要完整 Skill 生命周期，还是先实现 `PUBLISHED/YANKED` 两种状态？
6. “我的 Skill”首版最重要的是版本管理、发布失败重试，还是安装/使用统计？
7. 搜索首版应优先增加哪些筛选和排序维度？
8. Star、订阅通知、评论回复和 namespace 协作的实现顺序是否合理？
9. 正式业务库继续使用 PostgreSQL，还是由于现有基础设施要求需要尽早迁移 MySQL？
10. 哪些 Skillhub 功能对当前内网用户是真实需求，哪些只是架构完整但暂时没有用户价值？

## 12. 最终建议

Skillify 当前核心路线可行，已经具备测试环境验证价值。Forgejo 负责提示词、脚本和 Release 制品，Skillify 负责搜索、安装入口、评论、评分和排行榜，这一职责划分可以继续保留。

下一阶段不应把主要精力放在 API 防护或复制 Skillhub 的完整企业治理，而应先把用户每天会用到的链路做完整：可靠上传、可恢复发布、源码和版本可查看、搜索容易、安装稳定、更新清晰、个人 Skill 可管理。真实测试闭环通过后即可小范围内网上线，再根据用户反馈补充版本中心、个人工作台、Star、订阅和 namespace 协作。

---

# 附录 A — Claude 联合评审补充意见（就绪判断 · SkillHub 对比 · 借鉴取舍）

- 追加人：Claude（Opus 4.8）
- 追加日期：2026-07-11
- 追加目的：在 GPT 评审基础上，① 补充独立复核结论；② 落实用户本轮新增约束；③ 给出借鉴取舍见解。**可执行的开发计划已抽入独立任务书**（交付 GPT 开发），本附录不含任务清单。
- 本附录不记录任何账号、令牌、数据库或服务器密码；所有真实连接信息一律用环境变量占位。

## A.0 本轮新增约束（用户裁决，覆盖前文相关假设）

| 维度 | 裁决 | 对计划的影响 |
| --- | --- | --- |
| 安全边界 | 内网环境，本阶段安全策略**只考虑前端**（路由/菜单可见性 + Keycloak 登录）。不做 API 额外防护、外网攻击面、内容安全扫描。 | GPT 的“安全扫描与治理”整体降为后置，不作为上线阻断项。 |
| 权限 | **已接入 RBAC**（前端菜单级）。 | 不重建 RBAC，仅做回归验证（B-2）。 |
| 业务数据库 | Skillify 业务库（`skill_index`/`skill_comments`/`skill_ratings`/`skill_events`/`skill_namespace_owners`）从 PostgreSQL **迁移到 DM8（达梦）**；**复用公司现有共享 DM8 实例**（新建 schema/用户）。 | 新增 M-DM 工作流；GPT 的“可能迁 MySQL”作废，改为确定迁 DM8。 |
| Forgejo 数据 | Forgejo **核心层保持 PostgreSQL 不变**。 | 部署改为“PG 只服务 Forgejo + DM8 服务 Skillify”的**拆库**，而非替换。 |
| 测试策略 | **放弃新增自动化测试门禁**，DM8 与闭环由 **Codex 端到端直接验证**（依据 §8 与 A.7 清单）。 | 测试类节点不写 pytest/vitest 新套件；现有 SQLite 单测保留为纯业务逻辑回归。 |
| 交付对象 | 开发交付 **GPT**；计划见独立任务书 `docs/skillify-dev-tasks-dm8-and-readiness-2026-07-11.md`。 | 本评审文档只保留就绪判断与借鉴取舍。 |

## A.1 Claude 独立复核结论

**与 GPT 一致：** 测试环境 **GO**；内网正式使用采用“闭环通过 → 小范围试用 → 部门推广 → 全量内网”分阶段。职责划分（Forgejo 管源码/Release 制品，Skillify 管索引/搜索/评论/评分/排行榜/安装入口）继续保留。

**补充与修正三点：**

1. **换库把 GPT 的 P1-1 升级为 P0。** GPT 建议“引入 Alembic”原为 P1；一旦确定迁 DM8，`Base.metadata.create_all`（`src/skillify/index/db.py:17-22`）在 DM8 上会直接踩到类型映射与保留字问题，**必须与换库同批引入 Alembic 基线**，否则建表即失败。因此 Alembic 在本计划中随 M-DM 一起变为 P0。
2. **好消息：迁移工作量可控（证据见 A.4）。** 代码对数据库高度可移植——ORM 只用可移植类型、搜索在 Python 内存里做、写路径用 SAVEPOINT 而非 `ON CONFLICT`。全仓库与 PostgreSQL 强绑定的 touch point 仅 6 处，业务数据访问全部收敛在 `index_db_url → make_engine → SQLAlchemy ORM` 一条链上。真正的不确定性集中在**外部 DM8 驱动/方言**，应作为第一个 spike 先打通（DM-1）。
3. **“前端隐藏 ≠ 后端放行”必须写进验收。** RBAC 只控制前端菜单可见性；验收时要同时确认：未授权用户在前端看不到“上传”入口，且后端对应 API 仍走 Keycloak JWT 独立验签（`skillify/web/auth.py`）。二者是两层，不能因为前端隐藏就默认后端安全。

## A.2 Claude 对 GPT §11 十个问题的回答（要点）

| # | 问题 | Claude 建议 |
| --- | --- | --- |
| 1 | 可否进测试并小范围上线 | 同意。M-DM + 阶段 A 闭环通过即可对种子用户开放。 |
| 2 | Web 上传是否默认 commit 到 Forgejo | 目标态是；但**不阻断首版**。首版保持 Release-only，C-3 再补 commit+tag，使 Web 与 Git 两条入口最终一致。 |
| 3 | 版本中心首版范围 | 版本列表 + 变更说明 + 指定版本安装为**必做**；diff 与 yank 次之。（C-1） |
| 4 | 索引重建按仓库还是全量 | **两者都要**：日常按仓库触发（webhook 补偿），运维提供全量扫描命令兜底。（A-2） |
| 5 | 是否需要完整生命周期 | 先只做 `PUBLISHED / YANKED` 两态，审核流后置。 |
| 6 | “我的 Skill”首版重点 | **发布失败重试 > 版本管理 > 使用统计**（先解决 P0-2 暴露的半发布问题）。（C-2） |
| 7 | 搜索首版优先维度 | 分页 + namespace/作者/标签筛选 + 按安装量/评分/更新时间排序。（C-4） |
| 8 | Star/订阅/评论回复/namespace 顺序 | Star → 订阅通知 → 评论回复 → namespace 聚合。（C-5） |
| 9 | 正式业务库选型 | **已定 DM8**（本轮裁决），不再讨论 MySQL。 |
| 10 | 哪些 Skillhub 功能是真需求 | 真需求：版本中心、我的 Skill、搜索筛选、发布重试。暂无用户价值：完整审核流、举报、安全扫描、K8s/HA、语义搜索。 |

## A.3 数据边界（DM8 版，替代 GPT §4 的落点判断）

| 数据 | 落点（迁移后） | 归属 |
| --- | --- | --- |
| Forgejo 用户/仓库/Release/Git 元数据 | **PostgreSQL**（Forgejo 自管，不动） | Forgejo |
| Skill 发布包 / checksum / artifact | Forgejo Release assets | Forgejo |
| `skill_index`（检索元数据/版本索引） | **DM8** | Skillify |
| `skill_comments` / `skill_ratings` / `skill_events` / `skill_namespace_owners` | **DM8** | Skillify |

**边界纪律：** 业务表**不得**写入 Forgejo 自有 schema；Skillify 也**不得**直接读写 Forgejo 的 PG 库（只经 Forgejo API）。两库物理分离后，升级/备份/回退相互独立。

## A.4 DM8 迁移可行性判断（评审结论）

**结论：迁移工作量可控。** 代码对数据库高度可移植，证据：

- `src/skillify/index/models.py`：只用 `JSON / DateTime(timezone=True) / String / Integer / UniqueConstraint`，**无** `JSONB / tsvector / ARRAY / ENUM` 等 PG 专有类型。
- `src/skillify/index/queries.py`：`search()` 在 Python 内存里做子串匹配，**无 `ILIKE`**；`leaderboard()` 在 Python 里排序；SQL 仅用 `max(id) + group_by + in_ + order_by`（可移植子集）。
- `src/skillify/index/ingest.py`：`upsert_release()` 用 `session.begin_nested()`（SAVEPOINT）+ 捕获 `IntegrityError` 回退更新，**无 `ON CONFLICT / RETURNING`**。
- 与 PG 强绑定的 touch point 仅 6 处；真正的不确定性集中在**外部 DM8 驱动/方言**，应作为第一个 spike 先打通。

> 6 处 touch point 明细、DM8 类型映射与保留字对策等**实现级细节，见独立任务书 §4**（`docs/skillify-dev-tasks-dm8-and-readiness-2026-07-11.md`），本评审文档不重复。

## A.5 开发任务书（已拆分为独立文档）

本附录的评审到此为止。**可执行的开发计划、里程碑、任务节点、DoD、验收清单、风险与开放项，已全部抽入独立任务书**，交付 GPT 开发：

- 📄 `docs/skillify-dev-tasks-dm8-and-readiness-2026-07-11.md`

该任务书自包含（DM8 技术要点、6 处 touch point、类型映射、M-DM/A/B/C 任务表、职责边界与编译级 DoD 一应俱全）。本评审文档只保留“是否就绪 / 与 SkillHub 对比 / 借鉴取舍”等评审性内容，不再重复任务清单，避免两处任务来源产生漂移。

## A.6 借鉴 SkillHub 的取舍（Claude 见解，决定 C 阶段排序）

> 结论：不追平 SkillHub。SkillHub 的“完整”大多是**面向外网公开注册中心**的必要开销，对内网用户没有对应价值。值得借鉴的**不是功能，是它替你做过的两类产品决策**：① skill 的版本/状态怎么呈现，② 个人怎么管理自己的 skill。

**认同并提前（写进 C 优先级）：**

1. **Web 上传进 Git 历史（C-3，P1，最该早做）** —— 这不是普通功能缺口，而是 Skillify 架构**自我矛盾的唯一裂缝**：立论是“Git/Forgejo = 唯一真相源”（PLAN.md §1），但 Web 上传只生成 Release、不 commit 源码，等于在核心链路上开了个绕过真相源的口子。修它是为了让 Skillify 自圆其说，**优先级高于任何 SkillHub 功能对齐**。
2. **版本中心（C-1，P1）** —— SkillHub 的 `PUBLISHED/YANKED/...` 状态机与版本列表/diff/指定版本安装，值得抄的是**产品决策**，不是代码。Skillify 后端已能存多版本、前端只显示最新——地基有了、决策没做。首版落 `PUBLISHED/YANKED` 两态即可，审核流后置。
3. **我的 Skill 工作台（C-2，P2）** —— 借鉴 SkillHub 的信息架构（My Skills/My Namespaces），首版重点是**发布失败重试**。

**刻意降级（与 GPT 排序不同）：**

- **搜索下沉 SQL（C-4）由“高”降到 P3。** GPT 因 SkillHub 搜索厚重而列高优先；但内网几十到几百个 skill，现有 Python 内存子串搜索（`queries.py`）又快又够用，能撑很久，还省去趟 DM8 分页/like 语法差异。**数据量真涨了再做。**

**坚决不抄（比 GPT 更强硬）：**

- **不抄 RBAC/治理。** SkillHub 近期提交（`SUPER_ADMIN role guard`、`review-workflow`、`scanner`）显示它把复杂度预算大量花在自建权限/审核/扫描上；而 Skillify 已把这块**外包给公司 Keycloak + .NET RBAC**——这是更干净的架构分工，不是缺失。
- **不为对齐 SkillHub 牺牲 Forgejo + per-skill venv 隔离。** 不可变构件 + checksum + 每 skill 独立 uv venv，在内网/离线场景比平台化存储更优，是 Skillify 的**护城河，不是短板**。
- **不抄它的技术栈厚度**（43 migration / 43 Playwright / 15 workflow）——那是公开产品的养护成本，内网 MVP 照抄只会拖垮迭代。
