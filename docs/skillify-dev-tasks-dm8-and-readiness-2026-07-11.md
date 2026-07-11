# Skillify 开发任务书 · DM8 迁移与内网上线就绪

- 版本：v1（2026-07-11）
- **交付开发：GPT**（负责代码开发 + 编译级自校验）
- **测试环境搭建与端到端验收：用户 + Codex**（GPT 不执行）
- 评审依据、SkillHub 对比与借鉴取舍：见同目录 `review-test-production-readiness-skillhub-comparison-2026-07-11.md`（**本任务书不重复评审内容**）
- 纪律：不记录任何账号 / 令牌 / 数据库或服务器密码；所有真实连接信息一律环境变量占位。

---

## 1. 范围与硬约束

| 维度 | 约束 |
| --- | --- |
| 目标 | ① 把 Skillify 业务库从 PostgreSQL 迁到 **DM8（达梦）**；② 完成测试环境闭环所需代码；③ 内网上线就绪；④ 迭代核心产品体验。 |
| 业务库 | 5 张业务表（`skill_index`/`skill_comments`/`skill_ratings`/`skill_events`/`skill_namespace_owners`）迁到 **共享 DM8**（新建 schema/用户，**空表起步、无历史数据**）。 |
| Forgejo | 核心层**保持 PostgreSQL 不变**；Skillify 与 Forgejo **两库物理分离**。 |
| 建表方式 | 已提供一键建表脚本 `infra/dm8-init/01-skillify-schema.sql`（用户自行导入内网 DM8）。**首版不做 Alembic**（DM-7 后置）。 |
| 安全 | 内网环境，本阶段安全**只做前端**（路由/菜单可见性 + Keycloak 登录）。不做 API 额外防护、外网攻击面、内容安全扫描。 |
| 权限 | 已接入 RBAC（前端菜单级），只做回归验证，不重建。 |
| 测试 | **不新增自动化 DM8 测试门禁**；DM8/闭环由 Codex+用户在测试环境验收。现有 SQLite 单测保留为业务逻辑回归。 |

---

## 2. 开发者职责边界与交付判据（GPT 必读）

**职责划分：** GPT 只做**代码开发 + 编译级自校验**，不搭建测试环境，不假设本机存在可运行的 DM8 / Forgejo / Keycloak / devpi 实例。测试环境搭建、DM8 导入、真实闭环与端到端验收由**用户 + Codex**负责。

> 因此：第 6 节任务表的“测试环境验收”列，是交给 Codex+用户执行的判据，**GPT 不执行、也不以其作为完成标志**。GPT 的完成标志统一为下方 DoD。

**GPT 每个节点通用交付判据（DoD，编译级）：**

1. **可编译/可导入**：后端 `uv sync` 成功、相关模块 `python -c "import ..."` 导入无误；前端 `npm run build` 通过。
2. **类型检查**：`npx vue-tsc --noEmit` 零错误（A-3 完成后作为常驻门禁）。
3. **本地单测绿**：`uv run pytest -q`（**SQLite** 后端，纯业务逻辑）与 `npm test -- --run`（vitest）全通过；改动的方言无关逻辑补 SQLite 单测。
4. **DM8 专有路径只保证“编译 + 导入 + 静态正确”**：无法在无 DM8 时运行的代码（连接、方言、类型往返、SAVEPOINT 行为等）只需静态成立并写清假设，**运行期验证明确标注“留测试环境（Codex）”**。
5. **每次交付附自检说明**：改了什么、跑了哪些自校验命令及结果、哪些判据留给测试环境。
6. **红线**：不把真实连接串/令牌写进代码或提交，一律环境变量占位；不在业务代码里绕过第 3 节数据边界。

> 建表脚本 `infra/dm8-init/01-skillify-schema.sql` 属“无 DM8 无法执行”类，GPT 只做语法/结构静态核对（与 `src/skillify/index/models.py` 逐列对齐），实际导入与验证由测试环境完成。

---

## 3. 数据边界（编码红线）

| 数据 | 落点 | 归属 |
| --- | --- | --- |
| Forgejo 用户/仓库/Release/Git 元数据、Skill 发布包/checksum/artifact | **PostgreSQL + Forgejo Release**（Forgejo 自管） | Forgejo |
| `skill_index` / `skill_comments` / `skill_ratings` / `skill_events` / `skill_namespace_owners` | **DM8** | Skillify |

- 业务表**不得**写入 Forgejo 自有 schema；Skillify **不得**直接读写 Forgejo 的 PG 库（只经 Forgejo API）。
- 业务数据访问全部收敛在 `index_db_url → make_engine → SQLAlchemy ORM` 一条链上，不要在别处新开 DB 连接。

---

## 4. DM8 迁移技术要点（编码必读）

### 4.1 与 PostgreSQL 强绑定的 6 处 touch point（改动面）

| # | 位置 | 现状 | 迁移动作 |
| --- | --- | --- | --- |
| 1 | `infra/docker-compose.yml:70` | `SKILLIFY_INDEX_DB_URL: postgresql+psycopg://...@db:5432/skillify_index` | 指向共享 DM8（`dm+dmPython://...`，`.env` 占位） |
| 2 | `infra/postgres-init/01-create-skillify-index-db.sql` | 在 Forgejo PG 里 `CREATE DATABASE skillify_index` | 删除该语句；Forgejo PG 只留自身库；DM8 侧改由 `dm8-init/01-skillify-schema.sql` 初始化 |
| 3 | `pyproject.toml:16` | `psycopg[binary]>=3.1` | 增加 `dmPython` + DM8 SQLAlchemy 方言依赖；`psycopg` 保留（PG 场景仍可用，可移入可选组） |
| 4 | `src/skillify/common/config.py:27` | 注释写死 “Postgres index DB” | 更新为 DM8；`index_db_url` 逻辑本身方言无关，无需改代码 |
| 5 | `src/skillify/index/db.py:17-22` | `Base.metadata.create_all` | 生产/测试路径**跳过 `create_all`**（表已由 SQL 建好）；`create_all` 仅保留给 SQLite 单测 |
| 6 | `infra/README.md:65` | `psql ... skillify_index` 初始化说明 | 改为“向共享 DM8 导入 `dm8-init/01-skillify-schema.sql`”步骤 |

### 4.2 类型映射与风险（DM-3 逐项落实）

| 项 | PG 行为 | DM8 关注点 | 对策 |
| --- | --- | --- | --- |
| 自增主键 `id` | `IDENTITY` | DM8 用 `IDENTITY(1,1)`，方言需正确生成/回读 | DM-1 确认方言对 `autoincrement` 支持 |
| JSON 列 `tags`/`orchestration` | `JSON` | DM8 JSON 支持有限，SQL 脚本落 `CLOB` 文本存储 | 确认 SQLAlchemy `JSON` 序列化往返一致 |
| 布尔列 `success` | `boolean` | DM8 无原生 boolean，脚本用 `BIT`；三态 True/False/None | 确认三态往返正确 |
| 带时区时间戳 `*_at` | `timestamptz` | `TIMESTAMP WITH TIME ZONE` 语义 | 确认存取 UTC 无偏移 |
| 保留字列 `name`/`version` | PG 可识别 | DM8 可能视为保留字 | 见脚本文末“保留字回退方案”；加引号后**方言须同样加引号保持大小写一致** |
| SAVEPOINT | 支持 | `upsert_release` 用 `session.begin_nested()` | DM-4 并发/幂等场景验证 |
| 唯一约束冲突 | `IntegrityError` | DM8 驱动抛错是否被 SQLAlchemy 归一为 `IntegrityError` | DM-4 验证 upsert 回退分支触发 |
| 空串处理 | `''` 即空串 | DM8 若为 Oracle 兼容模式会把 `''` 当 NULL，冲突 `NOT NULL DEFAULT ''` | 见脚本头注释第 2 条；实例模式由测试环境确认 |
| 分页/子串搜索（C-4 时） | `LIMIT/OFFSET`+`ILIKE` | DM8 分页/大小写 like 语法差异 | 用方言无关的 SQLAlchemy 表达式，避免手写 SQL |

### 4.3 可移植性现状（利好，减少改动）

- ORM（`models.py`）只用可移植类型；`queries.py` 的 `search()` 在 Python 内存里做子串匹配（无 `ILIKE`）、`leaderboard()` 在 Python 里排序；`ingest.py` 的 upsert 用 SAVEPOINT + `IntegrityError`（无 `ON CONFLICT`/`RETURNING`）。业务逻辑基本方言无关，改动集中在上面 6 处 + 类型校验。

---

## 5. 里程碑与出口标准

| 里程碑 | 内容 | 出口标准（测试环境验收） |
| --- | --- | --- |
| **M-DM** 换库（P0，前置） | 驱动/方言 → 导入建表 → 类型/保留字适配 → 读写验证 → 部署拆库 | 共享 DM8 建齐 5 表；三条写入路径 + 读路径由 Codex 验证一致；`postgres-init` 不再建 `skillify_index`；compose 指向 DM8 |
| **A** 测试闭环（P0） | 完整部署入口、发布可恢复、修类型门禁、三入口真实闭环 | 一套 compose 拉起全部组件；发布中断可重试、索引可重建；闭环清单全过 |
| **B** 内网上线（P0/P1） | 备份恢复、RBAC 回归、运维文档、种子灰度 | 三库各一次备份/恢复；未授权看不到上传入口且后端 JWT 独立拒绝；具备回退/恢复说明 |
| **C** 核心体验（迭代，不阻断首版） | 见 6.4，按优先级分批 | 每项独立可上线 |

关键路径：**M-DM → A → B**；C 与前序按依赖并行。

---

## 6. 任务清单（工作量档：S≈0.5–1d / M≈1–3d / L≈3–5d）

### 6.1 M-DM 换库工作流

| ID | 任务 | 依赖 | 档 | 测试环境验收（Codex+用户，GPT 不执行） |
| --- | --- | --- | --- | --- |
| DM-1 | **[Spike]** 打通 DM8 驱动与 SQLAlchemy 方言：确认 `dmPython` + DM8 方言在内网可获取/可装；确定连接 URL 形态；用 Skillify 业务用户导入 `infra/dm8-init/01-skillify-schema.sql` 建齐 5 表并跑通脚本末尾验证清单 | — | M | 产出可连接 URL 模板 + 锁定依赖版本；5 表建成、demo 行插读删成功 |
| DM-2 | 依赖与配置：`pyproject.toml` 增加 DM8 驱动+方言；`config.py` 注释更新为 DM8；`index_db_url` 用 `dm` 方言启动后端、`db.py` 生产路径**跳过 `create_all`**，`create_all` 仅留给 SQLite 单测 | DM-1 | S | 后端以 DM8 URL 启动不报错，不再尝试自动建表 |
| DM-3 | 类型/兼容校验（见 4.2 + SQL 头注释）：CLOB(JSON) / BIT(boolean) / TIMESTAMP WITH TIME ZONE / IDENTITY / 空串模式 / 保留字 name·version 在本实例上与 ORM 往返一致 | DM-2 | M | 每列插入读取无偏移/截断/找不到列 |
| DM-4 | 写路径语义验证：`upsert_release`（SAVEPOINT+幂等+并发）、`upsert_rating`、namespace claim、events 在 DM8 上与 PG 一致 | DM-3 | M | 重复 (ns,name,version) 更新而非报错；重复评分就地更新；唯一冲突走 `IntegrityError` 回退分支 |
| DM-5 | 读路径验证：`list_latest`/`get_versions`/`search`/`leaderboard` 在 DM8 结果正确（含中文描述子串搜索、多版本取最新、三个排行榜维度） | DM-3 | S | 结果与预期一致 |
| DM-6 | 部署拆库：`infra/postgres-init/01-*.sql` 删除 `CREATE DATABASE skillify_index`；compose `SKILLIFY_INDEX_DB_URL` 指向共享 DM8（`.env` 占位）；`infra/README` 改为导入 `dm8-init/01-skillify-schema.sql` 步骤 | DM-1 | M | 起栈后 Forgejo 用 PG、Skillify 用 DM8，互不干扰 |
| DM-7 | **[后置，C 阶段前]** 引入 Alembic：以当前 SQL 结构为基线 stamp，供后续加列（版本中心/Star 等）走迁移；首版可不做 | DM-6 | S | `alembic stamp` + 首个增量 migration 可 upgrade/downgrade |

### 6.2 阶段 A 测试闭环

| ID | 任务 | 依赖 | 档 | 测试环境验收（Codex+用户） |
| --- | --- | --- | --- | --- |
| A-1 | 完整部署入口：compose 增加 `skillify-web` 服务 + 前端静态站 + 统一反向代理，一套命令拉起全部组件 | DM-6 | L | 单命令起栈，浏览器可访问完整 Skillify |
| A-2 | 发布可恢复性：发布步骤状态记录 + 同版本幂等重试 + 缺失 Release asset 补传 + 从 Forgejo Release 重建 `skill_index`（按仓库触发 + 全量扫描命令）+ 发布失败释放 namespace 占用/管理员修复命令 | DM-4 | L | 人为中断发布后可续/重发布不留半成品；索引可重建 |
| A-3 | 前端类型门禁：修复 21 个 `vue-tsc` 错误，`type-check` 纳入构建/CI（**纯编译级、无依赖，建议最先做**） | — | M | `npx vue-tsc --noEmit` 零错误 |
| A-4 | 三入口真实闭环：Web 上传 / CLI publish / Git tag webhook 三路径产出一致的 Release 结构与索引 | A-1, A-2, DM-5 | M | 闭环清单全过（见评审文档 §8） |

### 6.3 阶段 B 内网上线

| ID | 任务 | 依赖 | 档 | 测试环境验收（Codex+用户） |
| --- | --- | --- | --- | --- |
| B-1 | 备份与恢复演练：DM8 业务库 + Forgejo PG + devpi 各一次备份/恢复；文档化 | A-1 | M | 恢复后数据完整、服务可用 |
| B-2 | RBAC/登录回归：Keycloak 登录 + 菜单可见性 + **后端 JWT 独立校验**；未授权用户看不到上传入口且直接调 API 被拒 | A-1 | S | 授权/未授权两类用户行为符合预期 |
| B-3 | 运维与回退文档：版本发布、回退、数据恢复、用户问题处理说明 | B-1 | S | 文档可被非作者按步骤执行 |
| B-4 | 种子用户灰度：限制用户/namespace 数量，观测上传/安装成功率、索引一致性 | A-4, B-1, B-2 | S | 一周试用无 P0 问题 |

### 6.4 阶段 C 核心体验（迭代，不阻断首版；排序理由见评审文档 §A.6）

> 先补 Skillify 架构自洽裂缝（C-3），再吸收 SkillHub 有产品价值的版本中心/个人工作台（C-1/C-2），社区其次；**搜索下沉 SQL（C-4）刻意后置**——内网数据量小，现有内存搜索够用，数据量真涨了再做。

| 优先级 | ID | 任务 | 依赖 | 档 | 说明 |
| --- | --- | --- | --- | --- | --- |
| P1 | C-3 | Web 上传进入 Git 历史：解压后 commit+tag 再生成 Release，统一两入口 | A-2 | M | 补架构裂缝，让 Web 上传也进真相源 |
| P1 | C-1 | 版本中心：版本列表/时间线 + 变更说明 + 指定版本安装（必做）；diff + yank（次做） | A-4 | L | 首版落 `PUBLISHED/YANKED` 两态即可 |
| P2 | C-2 | 我的 Skill 工作台：我的 skill/namespace + 发布结果 + **失败重试**（优先）+ 安装/使用统计 | A-2 | L | 信息架构参考 SkillHub My Skills |
| P2 | C-5 | 社区：Star/收藏 → 订阅通知 → 评论回复/管理（按此顺序分批） | A-4 | L | Star/订阅最先做 |
| P3 | C-6 | 排行榜时间维度：本周/本月/全部 | DM-5 | S | — |
| P3 | C-4 | 搜索筛选下沉 SQL：分页 + namespace/作者/标签筛选 + 安装量/评分/更新时间排序（替换 in-Python `search()`）| DM-5 | M | 用方言无关表达式，避开 DM8 分页/like 语法差异 |

---

## 7. DM8 专项测试环境验收清单（供 Codex+用户；GPT 不执行）

- [ ] 共享 DM8 上导入 `01-skillify-schema.sql` 建齐 5 表并跑通脚本末尾验证清单。
- [ ] 每列类型往返：`tags`/`orchestration`（JSON）、`success`（True/False/None 三态）、`published_at`（带时区、UTC 无偏移）、自增主键连续。
- [ ] 保留字列 `name`/`version` 写入与按其过滤/排序均无语法错误。
- [ ] `upsert_release` 重复同版本 → 就地更新不报错；模拟并发 redelivery → 无重复行、无未捕获异常。
- [ ] `upsert_rating` 同用户重复评分 → 就地更新；`skill_namespace_owners` 首次占用后他人写入被拒。
- [ ] `list_latest` 多版本取最新、`search` 中文子串、三个 `leaderboard` 维度结果正确。
- [ ] 重启后业务数据完整；Forgejo PG 与 DM8 各自独立备份/恢复成功。
- [ ] 前端隐藏上传入口的未授权用户，直接请求上传 API 被后端 JWT 拒绝（前后端两层各自生效）。

---

## 8. 风险登记

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| DM8 SQLAlchemy 方言/`dmPython` 版本兼容或授权不可得 | 高 | DM-1 作为第一个 spike 先打通；不通立即上报，暂以 PG 兜底测试环境 |
| 共享 DM8 兼容模式导致 `''`→NULL 或类型映射异常 | 中 | DM-3 逐列往返验证；见 SQL 头注释；实例模式由测试环境确认 |
| 未新增自动化 DM8 门禁，回归靠人工 | 中 | 保留 SQLite 单测护业务逻辑；DM8 相关改动强制过第 7 节清单 |
| A-2 发布可恢复性范围较大，拖累关键路径 | 中 | 首版只做“状态记录 + 幂等重试 + 索引重建”，消息队列后置 |

---

## 9. 开放项（DM-1 时现场确认，不阻塞起步）

- 内网能否获取 `dmPython` 驱动与 DM8 SQLAlchemy 方言（离线 wheel / 私有 devpi）。
- 共享 DM8 实例的**兼容模式**（决定空串 `''` 是否被当 NULL，见 SQL 头注释第 2 条）。

> 默认推进：空表起步、`.env` 占位连接串、DM-1 先验证驱动与实例模式，遇阻回问。**A-3（修 vue-tsc 错误）完全在 GPT 自校验范围内、无依赖，建议最先起步。**
