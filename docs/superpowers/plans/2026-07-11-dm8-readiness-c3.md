# Skillify DM8、内网上线就绪与 C-3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 M-DM、A、B、C-3 顺序完成 DM8 拆库、完整部署、可恢复发布、运维交付和 Web 上传 Git 历史。

**Architecture:** Forgejo 自主管理 PostgreSQL、Git 和 Release；Skillify 仅通过标准接口使用 Forgejo，并只在外部 DM8 保存五张业务表。发布恢复从 Forgejo Release 和 asset 推导，不增加任务表；Web 上传通过隔离 Git 工作区提交源码。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、dmPython/DM SQLAlchemy dialect、Typer、Vue 3、Vite、Nginx、Docker Compose、Forgejo 10、PostgreSQL 16、devpi。

## Global Constraints

- DM8 空表起步，不迁移历史数据，不引入 Alembic。
- Forgejo PostgreSQL 和 Skillify DM8 物理、逻辑分离。
- Skillify 不直接读写 Forgejo PostgreSQL。
- DM8 只包含现有五张业务表。
- 不新增自动化测试用例；只运行现有回归和编译门禁。
- 所有真实连接信息使用环境变量占位。
- 真实 DM8、Docker 和外部系统 E2E 留独立测试窗口。

---

### Task 1: DM8 驱动与建表边界

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/skillify/common/config.py`
- Modify: `src/skillify/index/db.py`
- Review: `infra/dm8-init/01-skillify-schema.sql`

**Interfaces:**
- Consumes: `SkillifyConfig.index_db_url`
- Produces: `make_engine(db_url: str)` 和仅 SQLite 自动建表的 `init_db(engine)`

- [ ] 静态确认可用于 SQLAlchemy 2 的 DM8 驱动与方言包，并记录无法在本机运行 DM8 的限制。
- [ ] 更新后端依赖和锁文件，确保普通模块导入不要求立即连接 DM8。
- [ ] 把配置说明从 PostgreSQL 业务库改为外部 DM8。
- [ ] 修改 `init_db()`，仅 `engine.dialect.name == "sqlite"` 时调用 `create_all`。
- [ ] 逐列核对 DM8 SQL 与 ORM 五张表，不增加第六张业务表。
- [ ] 运行 `uv sync --frozen`、相关模块 import 和现有后端测试。

### Task 2: Forgejo PostgreSQL 与 DM8 部署拆分

**Files:**
- Delete: `infra/postgres-init/01-create-skillify-index-db.sql`
- Modify: `infra/docker-compose.yml`
- Modify: `infra/.env.example`
- Modify: `infra/README.md`
- Modify: `tests/test_infra_compose.py` only if existing assertions must follow the new topology; do not add new test cases

**Interfaces:**
- Consumes: `SKILLIFY_INDEX_DB_URL`
- Produces: Forgejo 只连 Compose PostgreSQL、Skillify 服务只连外部 DM8 的配置

- [ ] 删除 Forgejo PostgreSQL 中创建 `skillify_index` 的初始化 SQL。
- [ ] 增加 DM8 URL 环境变量占位并移除业务库 PG 拼接。
- [ ] 更新 README 为 DIsql 导入 `infra/dm8-init/01-skillify-schema.sql`。
- [ ] 保证 Compose 不声明 DM8 容器，也不把 DM8 凭据写入仓库。
- [ ] 运行现有 Compose 静态检查。

### Task 3: 修复前端类型门禁

**Files:**
- Modify: `web/package.json`
- Modify: `web/src/components/ContactSelector.vue`
- Modify: `web/src/views/backend/auth/**/*.vue`
- Modify: `web/src/api/backend/rbac/types/index.ts` or the narrow shared type source required by the errors

**Interfaces:**
- Produces: `npm run type-check` and a build script that executes type checking before Vite

- [ ] 修复 Element Plus checkbox、tag type、tree filter 和 switch 回调类型。
- [ ] 修复 RBAC 当前用户被推断为 `never` 的类型定义。
- [ ] 增加 `type-check` 脚本并纳入 `build`。
- [ ] 运行 `npx vue-tsc --noEmit`、Vitest 和 Vite build，确认零类型错误。

### Task 4: 完整 Compose 产品入口

**Files:**
- Modify: `Dockerfile`
- Create: `web/Dockerfile`
- Create: `web/nginx.conf`
- Create: `infra/nginx/default.conf.template` only if runtime upstream templating is needed
- Modify: `infra/docker-compose.yml`
- Modify: `infra/.env.example`
- Modify: `infra/README.md`

**Interfaces:**
- Produces: `skillify-web` 后端服务、`frontend` SPA/Nginx 服务和统一用户访问端口

- [ ] 将 Python 镜像整理为可通过 command 启动 webhook 或 web 的通用运行镜像。
- [ ] 创建前端多阶段构建镜像和 SPA history fallback。
- [ ] 将 API/docs/health 路径反向代理到 `skillify-web`。
- [ ] 在 Compose 增加 `skillify-web` 与 `frontend`，复用同一 Forgejo 和 DM8 配置。
- [ ] 更新启动、配置和静态验收说明。
- [ ] 在无 Docker 环境运行 YAML/Compose 静态检查并记录实机验收待办。

### Task 5: Forgejo Release 幂等恢复

**Files:**
- Modify: `src/skillify/publish/forgejo_client.py`
- Modify: `src/skillify/publish/publisher.py`
- Modify: `src/skillify/cli/publish_cmd.py`
- Modify: `src/skillify/webhook/handler.py` if result wording changes
- Modify: existing fake Forgejo support only as required to keep current tests running; do not add test cases

**Interfaces:**
- Produces: `publish_skill_dir(...) -> PublishResult`，相同 checksum 可恢复缺失资产并重新索引

- [ ] 扩展 Release 模型以读取 body/draft 等恢复所需字段。
- [ ] 用 Release body 中的 checksum 判断相同内容或不可覆盖冲突。
- [ ] 对相同内容检查三个标准 asset，仅补传缺失项。
- [ ] 完整 Release 重试时重新执行索引写入并返回幂等结果。
- [ ] 保持不同内容的同版本发布拒绝覆盖。
- [ ] 运行现有发布、安装、依赖和 webhook 回归。

### Task 6: 索引重建与 namespace 修复工具

**Files:**
- Create: `src/skillify/index/rebuild.py`
- Create: `src/skillify/cli/repair_cmd.py`
- Modify: `src/skillify/cli/main.py`
- Modify: `src/skillify/publish/forgejo_client.py`
- Modify: `src/skillify/index/ownership.py`

**Interfaces:**
- Produces: 按 `namespace/name` 和全量重建索引；显式释放错误 namespace 占用

- [ ] 从 `.artifact.json` 和 checksum asset 解析可重建的 Release 元数据。
- [ ] 实现单仓库重建，所有写入仍走 `make_engine` 和 ORM upsert。
- [ ] 通过 Forgejo API 分页枚举组织/仓库并实现全量重建。
- [ ] 增加 Typer repair 命令，输出成功、跳过和失败统计。
- [ ] 增加带明确确认参数的 namespace 释放操作。
- [ ] 运行 CLI import、OpenAPI 和现有后端回归。

### Task 7: 阶段 B 运维交付

**Files:**
- Create: `docs/operations-dm8-forgejo-devpi.md`
- Create: `docs/operations-release-recovery.md`
- Create: `docs/internal-pilot-checklist.md`
- Modify: `infra/README.md`

**Interfaces:**
- Produces: 可由测试窗口执行的备份恢复、回退、修复、RBAC 回归和灰度清单

- [ ] 编写 DM8 `dexp/dimp` 占位命令和恢复核验步骤。
- [ ] 编写 Forgejo PostgreSQL 与 `/data` 一致性备份恢复步骤。
- [ ] 编写 devpi 导出/导入或数据卷备份恢复步骤。
- [ ] 编写版本发布、回退、索引重建和 namespace 修复步骤。
- [ ] 编写 Keycloak/Rbac.Api 回归与种子用户记录模板，不填造运行结果。
- [ ] 扫描文档，确认没有真实凭据或服务器连接信息。

### Task 8: C-3 Web 上传进入 Forgejo Git 历史

**Files:**
- Create: `src/skillify/publish/git_source.py`
- Modify: `src/skillify/web/upload_service.py`
- Modify: `src/skillify/common/config.py` if Git identity/default branch config is required
- Modify: `Dockerfile` to include runtime Git
- Modify: `infra/README.md`

**Interfaces:**
- Produces: `push_skill_source(skill_dir, cfg, org, repo, tag, uploader)`，只通过 Forgejo Git 通道写源码

- [ ] 在隔离临时目录 clone Forgejo 仓库并复制完整 Skill 源码。
- [ ] 设置非敏感提交身份并创建一个源码 commit。
- [ ] 使用子进程环境传递认证，不把 token 放进 URL、日志或 DM8。
- [ ] 推送默认分支和版本 tag；相同 tag 幂等，不同内容拒绝覆盖。
- [ ] Web 上传在 Release 发布前调用该接口；CLI publish 和 webhook 语义不变。
- [ ] 所有成功/失败路径清理临时 Git 工作区。
- [ ] 运行模块 import、现有 Web 上传回归和完整后端回归。

### Task 9: 最终门禁与 Opus 评审材料

**Files:**
- Modify: `docs/skillify-dev-tasks-dm8-and-readiness-2026-07-11.md` only to append actual completion status without rewriting user/Opus content
- Create: `docs/development-delivery-dm8-readiness-c3-2026-07-11.md`

**Interfaces:**
- Produces: 代码变更摘要、门禁证据和留测试窗口事项

- [ ] 运行 `uv sync --frozen` 和 Python import 检查。
- [ ] 运行完整现有 `uv run pytest -q`。
- [ ] 运行 `npm test -- --run`、`npm run type-check` 和 `npm run build`。
- [ ] 验证 `/openapi.json` 可生成。
- [ ] 运行 Compose/YAML、SQL/ORM 列对齐、`git diff --check` 和敏感信息扫描。
- [ ] 记录无法在本窗口执行的 DM8、Docker、真实三入口、备份恢复和灰度验收。
