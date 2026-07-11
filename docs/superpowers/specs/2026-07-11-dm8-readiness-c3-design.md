# Skillify DM8、内网上线就绪与 C-3 设计

## 目标

按 `M-DM -> A -> B -> C-3` 完成代码交付：将 Skillify 五张业务表迁到外部共享 DM8，补齐完整部署和可恢复发布，形成内网上线运维材料，并让 Web 上传的源码通过 Forgejo 标准接口进入 Git 历史。

## 硬约束

- DM8 空库起步，不迁移历史数据，不引入 Alembic。
- DM8 只保存 `skill_index`、`skill_comments`、`skill_ratings`、`skill_events`、`skill_namespace_owners`。
- Forgejo PostgreSQL、Git 对象、仓库、tag 和 Release 由 Forgejo 自管。
- Skillify 不直接读写 Forgejo PostgreSQL，只调用 Forgejo HTTP/Git 接口。
- C-3 不把 Git 文件、commit 或 Forgejo 元数据复制到 DM8。
- 不新增自动化测试用例；保留并运行现有测试、类型检查和构建门禁。
- 真实 DM8、Docker、Keycloak、Forgejo 和 devpi 联调留给独立测试窗口。

## M-DM 设计

Forgejo 继续使用 Compose 内 PostgreSQL。Skillify 的 `SKILLIFY_INDEX_DB_URL` 改为外部 `dm+dmPython://` 模板，所有业务访问继续经过 `index_db_url -> make_engine -> SQLAlchemy ORM`。

`init_db()` 仅在 SQLite 测试连接上调用 `Base.metadata.create_all()`；DM8 等非 SQLite 数据库必须先导入 `infra/dm8-init/01-skillify-schema.sql`，应用不自动改表。DM8 驱动和 SQLAlchemy 方言作为后端运行依赖声明，具体离线 wheel 与锁定版本由测试环境确认。

## 阶段 A 设计

Compose 增加 `skillify-web` 和前端 Nginx 服务。前端 Nginx 提供 SPA 静态文件并把 `/api`、`/healthz`、`/openapi.json` 和 `/docs` 代理到 `skillify-web`。DM8 是外部共享服务，不进入 Compose。

发布恢复以 Forgejo Release 自身为协调状态，不增加 DM8 表：发布器识别相同 tag 的 Release，checksum 相同则补传缺失 asset 并重建索引；checksum 不同则拒绝覆盖。Forgejo Release 仍是制品真相源。

提供按仓库和全量索引重建命令。重建从 Release 的 artifact manifest 和 checksum 资产读取数据，再通过现有 ORM upsert 到 DM8。namespace 首次占用若发布失败，提供显式修复命令，不在业务数据库中保存 Forgejo 发布任务。

修复现有 Vue 类型错误，并把 `vue-tsc --noEmit` 纳入前端构建脚本。

## 阶段 B 设计

提供以下运维文档：

- DM8、Forgejo PostgreSQL、Forgejo 数据目录和 devpi 的备份恢复步骤。
- 服务发布、回退、索引重建、namespace 修复和常见故障处理。
- Keycloak 登录、Rbac.Api 菜单和后端现有 JWT 校验回归清单。
- 种子用户灰度记录模板。真实演练结果不在开发阶段伪造。

## C-3 设计

Web ZIP 上传完成解压和校验后，通过 Forgejo 管理的 Git 通道创建一个包含完整 Skill 目录的 commit，并推送对应版本 tag，然后复用统一发布器创建或恢复 Release。

Git 写入通过隔离的临时工作目录执行，认证只通过子进程环境传递，不写入 remote URL、日志或 DM8。提交成功后，Forgejo 自己持久化 Git 数据。Git tag 已存在且指向不同内容时拒绝覆盖；相同内容的恢复操作保持幂等。

CLI publish 保持 Release 发布语义，Git tag webhook 保持从已有 Forgejo tag 打包。C-3 只修复 Web 上传没有源码历史的问题，不扩展版本中心或个人工作台。

## 错误处理

- DM8 未初始化时快速返回清晰错误，不尝试自动建表。
- Release 已存在且 checksum 一致时恢复缺失资产并重新索引。
- Release/tag 与上传内容冲突时保持不可变语义并拒绝覆盖。
- 索引失败不删除已完成的 Forgejo Git/Release；通过重建命令恢复。
- Git 临时目录无论成功失败都清理。

## 验证

开发阶段运行现有 `pytest`、Vitest、`vue-tsc`、Vite build、OpenAPI 生成和 Compose 静态检查。DM8 类型往返、真实容器启动、三入口闭环、备份恢复和灰度由后续独立测试窗口执行。
