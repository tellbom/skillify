# Skillify M-DM、A、B、C-3 开发交付

- 日期：2026-07-11
- 分支：`codex/dm8-readiness-c3`
- 设计：`docs/superpowers/specs/2026-07-11-dm8-readiness-c3-design.md`
- 计划：`docs/superpowers/plans/2026-07-11-dm8-readiness-c3.md`
- 约束：空 DM8、五张业务表、无 Alembic、无历史迁移、不新增测试用例

## 已完成

### M-DM

- 增加并锁定 SQLAlchemy 2 可加载的 `dmPython` 和 `dmSQLAlchemy`。
- `init_db()` 仅为 SQLite 临时测试库自动建表，DM8 必须导入初始化 SQL。
- 删除 Forgejo PostgreSQL 创建 `skillify_index` 的脚本和挂载。
- Compose 中 Skillify 服务统一读取外部 `SKILLIFY_INDEX_DB_URL`。
- DM8 仍只有任务书定义的五张业务表。

### 阶段 A

- Python 镜像可分别启动 webhook 和 `skillify-web`，并包含 C-3 所需 Git 客户端。
- 新增前端多阶段镜像、Nginx SPA、API/docs/health 反向代理。
- Compose 增加 `skillify-web` 和 `frontend`，入口默认为 `8080`。
- 前端 21 个 TypeScript/Vue 错误清零，`npm run build` 先执行 `type-check`。
- Release 使用 draft 作为未完成状态；相同 checksum 可补传缺失 asset，完成后转正式发布。
- 新增 `skillctl rebuild-index <namespace>/<name>` 和 `skillctl rebuild-index --all`。
- 新增 `skillctl release-namespace <namespace> --owner <owner> --yes`。
- Forgejo asset 下载自动使用配置的服务端基址，兼容容器内地址与外部 ROOT_URL 不同的部署。

### 阶段 B

- `docs/operations-dm8-forgejo-devpi.md`
- `docs/operations-release-recovery.md`
- `docs/internal-pilot-checklist.md`

文档只提供可执行步骤与记录模板，没有填造 DM8、Docker、备份恢复或灰度结果。

### C-3

- Web 上传可在校验后把完整源码提交到 Forgejo 默认分支并创建版本 tag。
- Git 使用临时工作区，成功和失败都会清理。
- token 通过 Git 子进程环境传递，不进入 remote URL、日志或 DM8。
- 已存在 tag 时按 Git tree 比较：相同源码幂等，不同源码拒绝覆盖。
- CLI publish 和 Git tag webhook 保持原有职责。

## 数据边界

- Forgejo PostgreSQL：Forgejo 自管。
- Forgejo Git、tag、Release、asset：Forgejo 自管。
- Skillify DM8：只保存五张业务表。
- Skillify 只调用 Forgejo API/Git，不直接连接 Forgejo PostgreSQL。
- DM8 不保存 Git 文件、commit、tag 或 Forgejo用户数据。

## 开发阶段门禁

| 命令 | 结果 |
| --- | --- |
| `uv sync --frozen` | 通过 |
| `uv run pytest -q` | 196 passed，2 skipped，2 warnings |
| `npm test -- --run` | 28 passed |
| `npm run build` | 通过，包含零错误 `vue-tsc --noEmit` |
| `python -m compileall -q src` | 通过 |
| FastAPI OpenAPI 生成 | 通过，11 个 path |
| Compose 现有静态检查 | 5 passed |
| `git diff --check` | 通过 |

保留告警：Starlette TestClient 弃用提示、Python 3.14 tar extraction 提示、Vite 大 chunk 和本机 npm 镜像配置提示。

## 留独立测试窗口

1. 用 DIsql 导入 DM8 初始化 SQL并验证五张表。
2. 验证 CLOB JSON、BIT 三态、时区、自增、中文、空串和保留字。
3. 验证 SAVEPOINT + `IntegrityError`、评分 upsert 和 namespace 并发语义。
4. 在 Linux Docker 构建并启动完整 Compose。
5. 验证 Web 上传 Git commit/tag、CLI publish、Git tag webhook 三入口。
6. 人为中断 Release asset 上传后恢复，并执行单仓库/全量索引重建。
7. 执行 DM8、Forgejo PostgreSQL + `/data`、devpi 的备份恢复演练。
8. 按种子试用清单完成浏览器、RBAC 和灰度验收。
