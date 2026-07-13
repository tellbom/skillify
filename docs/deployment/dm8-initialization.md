# DM8 初始化与验证

使用专用用户/schema（文档不记录密码），由 SYSDBA 创建后授予 `RESOURCE`，按 `01` 至 `05` 执行 `infra/dm8-init/*.sql`。

Windows DIsql 会按系统代码页读取脚本；直接读取仓库 UTF-8 文件会把中文注释错误解码并破坏语句边界，而且进程仍返回 0。部署时生成临时 GBK 副本后导入，仓库源文件保持 UTF-8。必须扫描输出中的“错误”，不能只检查退出码。

空 schema 导入后存在 8 表：`SKILL_INDEX`、`SKILL_COMMENTS`、`SKILL_RATINGS`、`SKILL_EVENTS`、`SKILL_NAMESPACE_OWNERS`、`SKILL_PUBLISH_JOBS`、`SKILL_STARS`、`SKILL_SUBSCRIPTIONS`。应用容器已实际读写。最终有 5 条成功索引数据；发布任务同时包含成功与预期冲突产生的失败状态；评论、评分、事件、收藏、订阅表均为 0，未被发布测试污染。

关键核验 SQL：

```sql
SELECT TABLE_NAME FROM USER_TABLES ORDER BY TABLE_NAME;
SELECT NAMESPACE,NAME,VERSION,AUTHOR,CHECKSUM,YANKED FROM SKILL_INDEX ORDER BY ID;
SELECT STATUS,COUNT(*) FROM SKILL_PUBLISH_JOBS GROUP BY STATUS;
SELECT COUNT(*) FROM SKILL_COMMENTS;
SELECT COUNT(*) FROM SKILL_RATINGS;
SELECT COUNT(*) FROM SKILL_EVENTS;
```

现有 SQL 是“从空 schema 构建”的事实源，不是可重复迁移脚本；在同一 schema 再执行会因对象已存在而失败。因此本次验证的幂等结论为“不幂等，符合空库初始化定位但不满足重复导入期待”，列为已知风险。

