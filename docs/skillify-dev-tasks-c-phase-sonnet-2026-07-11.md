# Skillify 开发任务书 · C 阶段（版本中心 / 我的 Skill / 社区 / 排行榜 / 搜索）

- 版本：v1（2026-07-11）
- **交付开发：Sonnet 5**（代码开发 + 编译级自校验）
- **最终统一评审：Codex（GPT 5.6）** —— 全量检索式复核 + DM8 运行期验收
- 前置：M-DM / 阶段A / 阶段B / C-3 已由前序开发完成并合并 main（评审通过：pytest 196 passed、vue-tsc 0、build 0、clean FF）。
- 依据：`docs/skillify-dev-tasks-dm8-and-readiness-2026-07-11.md`（总任务书）与 `review-test-production-readiness-skillhub-comparison-2026-07-11.md` §A.6（借鉴取舍）。本任务书只覆盖 C 阶段五个节点。

---

## 0. 起步前提（必读）

- **从已合并 C-3 的 main 起分支。** 若本地 `main` 看不到 `src/skillify/publish/git_source.py`，先 `git pull` 同步再开工，否则会基于陈旧基座。
- **schema 演进走方案A（用户裁决）：增量 SQL 文件，不引入 Alembic。** 进内网时按序号执行 `infra/dm8-init/01 → 02 → 03 …` 恢复基表 + 种子数据。
- `init_db()` 维持现状：**只对 SQLite `create_all`**，DM8 永远靠导入 SQL。不要改这个开关。
- DM8 运行期由 Codex 验收，Sonnet **不搭测试环境、不假设本机有 DM8/Forgejo/Keycloak**（DoD 见 §2）。

## 1. 方案A · schema 演进约定（本阶段最重要的纪律）

任何需要改表的节点，必须**同时产出下面两处，并保持列级一致**：

1. `src/skillify/index/models.py`（ORM）—— SQLite 单测经 `create_all` 由它建表，是**测试事实源**。
2. `infra/dm8-init/NN-<node>.sql`（新增增量文件）—— **DM8 事实源**。规则：
   - 类型对齐 01 脚本：`JSON→CLOB`、`bool→BIT`、`timestamptz→TIMESTAMP WITH TIME ZONE`、自增→`IDENTITY(1,1)`。
   - 保留字 `name`/`version` 沿用 01 的处理方式。
   - 只用 `ALTER TABLE ADD COLUMN` / `CREATE TABLE` / `CREATE INDEX`；新列给 `DEFAULT` + `NOT NULL`（避免历史行为空，注意 DM8 空串模式见 01 头注释）。
   - 需要种子数据时附幂等 `NN-<node>-seed.sql`（可重复导入不报错）。
3. **序号一旦分配即固定、不回收**（保证内网按序导入可复现）。本阶段预分配：

| 节点 | 增量 SQL | 是否改表 |
| --- | --- | --- |
| C-1 版本中心 | `02-c1-version-center.sql` | 是（ALTER skill_index） |
| C-2 我的 Skill | `03-c2-my-skills.sql`（**仅在确实需要新表时创建**，见 C-2） | 视需要 |
| C-5 社区 | `04-c5-community.sql` | 是（新表 + ALTER skill_comments） |
| C-4 搜索 | `05-c4-search-indexes.sql`（**仅在加索引时创建**） | 一般否 |
| C-6 排行榜时间维度 | — | 否 |

> **Codex 会核对**：`models.py` 与每个 `NN-*.sql` 列名/类型/约束逐列一致；从空库顺序执行 `01→05` 能重建全部结构。列不一致会导致"SQLite 测试过、DM8 建错表"，是本阶段头号回归风险。

## 2. 通用交付判据（DoD，编译级 —— 与前序一致）

1. 后端 `uv sync` + 相关模块 `python -c "import ..."` 通过；`uv run pytest -q`（SQLite）全绿，新增/改动逻辑补 SQLite 单测。
2. 前端 `npx vue-tsc --noEmit` 零错误、`npm run build` 通过；`npm test -- --run` 全绿。
3. 改表节点额外交付：`models.py` + 对应 `NN-*.sql`（+ 必要 seed），二者列级一致（自查并在交付说明中列出对照）。
4. DM8 运行期（类型往返、分页/like、时间函数、并发/唯一约束）**只保证静态成立**，运行期验证标注"留 Codex"。
5. 鉴权红线：写操作（yank、star、subscribe、评论删改、发布重试）必须走后端 Keycloak JWT 校验；前端按 RBAC 菜单/按钮可见性控制。**前端隐藏 ≠ 后端放行**，两层都要。
6. 数据边界：新数据落 DM8 五表体系；源码/版本仍只经 Forgejo API/Git，不直连 Forgejo PG。

## 3. 节点清单

> 建议开发顺序：**C-1 → C-2 → C-5 → C-6 → C-4**（C-4 P3 且需最谨慎处理 DM8 分页，放最后）。C-1/C-2/C-5 彼此独立，可并行。

### C-1 版本中心（P1）

- **Schema（`02`）**：`skill_index` 增列 `yanked BIT DEFAULT 0 NOT NULL`（首版只做 `PUBLISHED/YANKED` 两态，用布尔比 status 枚举更省）。
  - 变更说明**不落库**：直接读 Forgejo Release body（避免与 Forgejo 双写同一源）。
- **Backend**：
  - 版本列表/时间线：复用 `queries.get_versions`，返回按 `published_at` 倒序 + `yanked` 标记 + 变更说明（取自 Forgejo）。
  - 指定版本安装：确认/补全 CLI `skillctl install ns/name@version` 与 detail 接口的版本选择。
  - yank / unyank：写 `yanked` 标记（鉴权：作者或 namespace owner）。
  - 版本 diff：读两版本 Forgejo 源码（`get_raw_file` / git tree）计算差异，**纯计算不落库**。
  - **改 `queries.py`：`list_latest` / `search` / `leaderboard` 排除 `yanked`**（yanked 仍可显式按版本安装）。补 SQLite 单测覆盖"yank 后不出现在最新/搜索/榜单，但可指定安装"。
- **Frontend**：版本时间线、版本切换、diff 视图、yank 操作入口（RBAC 控制可见）。

### C-2 我的 Skill（P2）

- **Schema**：**首版尽量不新增表**。
  - "我的 skill / 我的 namespace"：查询 `skill_index`（`author=me`）+ `skill_namespace_owners`（`owner=me`）聚合。
  - "发布失败重试"：A-2 已把半成品发布留为 Forgejo **draft**；"我的失败发布"**派生自 Forgejo draft 列表**，重试 = 重新 `publish`（幂等续传，已实现）。**无需新表**。
  - install/使用统计：聚合 `skill_events`（已有 `occurred_at`/`event_type`/`machine_id`）。
  - 仅当产品明确要持久化"失败原因/时间/次数"时，才建 `skill_publish_jobs` 表并创建 `03-c2-my-skills.sql`；否则**不创建 03 文件**（序号保留占位）。
- **Backend**：My Skills / My Namespaces 聚合查询；重试端点复用现有 publish（鉴权：本人）。
- **Frontend**：My Skills / My Namespaces 页；发布结果与失败重试按钮。

### C-5 社区（P2，顺序：Star → 订阅 → 评论治理）

- **Schema（`04`）**：
  - 新表 `skill_stars`（`namespace,name,author,created_at`，唯一 `(namespace,name,author)`）。
  - 新表 `skill_subscriptions`（同结构，唯一 `(namespace,name,author)`）。
  - `skill_comments` 增列：`parent_id INT`（回复，NULL=顶层）+ `deleted BIT DEFAULT 0 NOT NULL`（软删）。
  - 通知：首版做**订阅关系 + "新版本"查询**即可；独立 `notifications` 表按排期后置（若做，纳入 `04` 或新 `06`）。
- **Backend**：star/unstar、subscribe/unsubscribe、评论回复、评论软删（作者/管理员，鉴权）。
- **Frontend**：Star 按钮+计数、订阅入口、评论树/回复/删除。

### C-6 排行榜时间维度（P3，无 schema）

- **Backend**：`leaderboard` 增加时间窗口参数（`week`/`month`/`all`），按 `skill_events.occurred_at` 过滤。**用方言无关的 SQLAlchemy 时间表达式**，避免手写 DM8 时间函数。补 SQLite 单测。
- **Frontend**：排行榜时间维度切换 tab。

### C-4 搜索下沉 SQL（P3，最后做，最谨慎）

- **Backend**：把 `queries.search()` 从 in-Python 子串匹配改为 SQL 查询：分页 + `namespace`/`author`/`tags` 过滤 + 按 `installs`/`rating`/`updated` 排序。
  - **DM8 关键**：一律用 SQLAlchemy 表达式（`.offset().limit()`、`func.lower(col).like(...)`），**绝不手写 SQL**，规避 DM8 分页与大小写 like 差异。
  - `tags` 是 CLOB(JSON)：标签过滤**首版仍在应用层**做（DM8 JSON 函数方言差异大），或后续再引规范化标签表（**本阶段不做**，避免过度设计）。
  - **Schema（`05`，可选）**：如需为 `author` 等排序/过滤列加索引才创建 `05-c4-search-indexes.sql`；`namespace`/`name` 已有索引。
- **Frontend**：搜索页分页 + 筛选 + 排序控件。
- 保留 in-Python `search()` 的行为等价性：改造后现有搜索单测应仍通过（或等价更新）。

## 4. 交给 Codex 的最终统一评审检查点（Sonnet 交付时对齐）

- `models.py` ↔ 每个 `NN-*.sql` 列名/类型/约束逐列一致；从空库顺序执行 `01→05` 可重建全部结构。
- `yanked` / 评论软删在 `list_latest` / `search` / `leaderboard` 生效；yanked 版本仍可显式安装。
- 新表唯一约束、外键/软删语义正确；所有写操作有后端 JWT 鉴权 + 前端 RBAC 可见性。
- 前端 `vue-tsc` 0 + `build` 通过；后端 pytest（SQLite）全绿。
- **DM8 运行期（Codex 执行）**：新列 `yanked`/`parent_id`/`deleted`（BIT）、新表 star/subscription 的类型往返、并发唯一约束、C-4 分页/like、C-6 时间过滤，在真实 DM8 上与 SQLite 行为一致。

---

> 一句话给 Sonnet：**每改一次表 = 改 `models.py` + 加一个对齐的 `infra/dm8-init/NN-*.sql`（+ 必要种子），二者列级一致**；能不建表就不建（C-2 派生 draft、C-4 标签应用层过滤）；写操作双层鉴权；DM8 运行期留给 Codex。按 C-1 → C-2 → C-5 → C-6 → C-4 推进。
