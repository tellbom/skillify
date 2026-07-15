# Skill 主分类设计

日期：2026-07-15  
状态：已确认（一个 Skill 只有一个主分类）

## 目标

为 Skillify 增加由平台维护的主分类体系。用户在 Web 统一发布流程的最终确认阶段必须选择一个启用分类；Skill 列表可以按分类筛选并展示分类。现有 `tags` 继续表达自由标签，不承担主分类语义。

## 方案比较与决策

1. 在 `skill_index` 增加 `category_id`：实现直接，但 `skill_index` 每个版本一行，会重复分类并允许同一 Skill 的不同版本分类不一致。
2. 使用分类基表和 Skill 级关联表：分类属于逻辑 Skill（`namespace/name`），版本发布不会复制分类。采用此方案。
3. 继续使用受控 `tags`：无需数据库迁移，但无法满足分类基表、启停和稳定外键关系的要求。

## 数据模型

新增 `skill_categories`：

- `id`：自增主键。
- `code`：稳定、唯一的英文代码，供 API 筛选使用。
- `name`：中文展示名。
- `description`：分类说明。
- `sort_order`：前端展示顺序。
- `enabled`：软停用标记；已关联数据保留，停用分类不能用于新发布。
- `created_at`、`updated_at`：审计时间。

新增 `skill_category_assignments`：

- `namespace`、`name`：逻辑 Skill 标识，联合主键，保证一个 Skill 只有一个主分类。
- `category_id`：指向 `skill_categories.id` 的外键。
- `assigned_at`、`updated_at`：首次分配与最近更新时刻。

分类不写入 `skill.yaml`，因此不改变 manifest v1，也不影响 Skill 包的跨平台安装语义。

预置分类为：写作、软件开发、数据分析、办公效率、调研与知识、设计与媒体、自动化与运维、其他，以及仅供历史数据占位的“未分类”。历史 Skill 和 CLI/Webhook 新发布若没有 Web 选择信息，自动关联“未分类”。

## 后端与 API

- `GET /api/categories` 返回启用且可选择的分类，按 `sort_order`、`id` 排序，不返回“未分类”。
- `GET /api/skills` 和 `GET /api/search` 增加可选 `category` 参数，值为分类 `code`。
- Skill 列表和详情响应增加可空 `category` 对象：`{id, code, name}`。
- `POST /api/skill-builds/{build_id}/publish` 请求增加必填 `categoryId`。后端在改变 Build 状态或调用 Forgejo 前校验分类存在、启用且可选择。
- Web 发布成功后，使用同一 Skillify 业务库将 `namespace/name` 的分类关系插入或更新。再次发布新版本可以更换主分类。
- 通用索引写入在不存在关联时补“未分类”，保证 Webhook、CLI、重建索引和历史数据都有确定分类，同时不得覆盖已有人工分类。

## 前端

- Skill 列表加载分类选项，提供主分类下拉框；选中后通过现有搜索请求发送 `category=<code>`，并参与清除筛选、分页复位和筛选标签展示。
- Build 最终预览与确认区域加载分类选项并提供必选下拉框。未选择分类时发布按钮禁用，并显示明确提示。
- 发布请求携带 `categoryId`。分类加载失败时不能发布，但 manifest 编辑和预览仍可继续。
- Skill 卡片展示主分类名称；没有关联的异常旧数据展示“未分类”。

## 数据迁移

新增 DM8 增量脚本创建两张表、索引、外键和幂等分类种子数据。脚本将 `skill_index` 中已有的不同 `namespace/name` 补为“未分类”。生产环境仍以 `infra/dm8-init/` SQL 为事实源；SQLite 测试数据库由 ORM 建表并自动写入相同种子。

## 错误处理

- 未传 `categoryId`：FastAPI 返回 `422`。
- 分类不存在、已停用或为系统“未分类”：发布接口返回 `422`，且不进入发布状态。
- 未知分类筛选代码：返回空结果，不泄漏停用分类。
- 发布外部步骤失败：不改变 Skill 分类；Build 恢复到可重试状态。
- Release 已成功但分类关系写入失败：沿用发布任务失败/可重试机制记录异常，避免静默成功。

## 测试范围

- 分类种子、排序、启停过滤、唯一主分类和更新分类。
- 索引写入默认“未分类”且不覆盖人工分类。
- 分类筛选、分页总数、列表/详情分类响应。
- 发布接口缺少、非法、停用分类校验，以及成功发布后的分类关系。
- 前端分类参数构造、筛选复位、发布按钮状态、请求载荷和错误展示。
- DM8 SQL/ORM 列级一致性、前端单测、后端全量测试、类型检查和构建。
