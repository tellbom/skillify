# Skillify 发布、回退与修复

## 正常发布

Web 上传、CLI publish 和 Git tag webhook 最终都生成同一组 Release asset：

- `<namespace>-<name>-<version>.tar.gz`
- `<namespace>-<name>-<version>.sha256`
- `<namespace>-<name>-<version>.artifact.json`

发布器先创建 draft Release，三个 asset 完整后再转为正式 Release，然后把派生元数据写入 DM8。

## 中断恢复

重新提交相同源码和相同版本：

- Release body 的 checksum 相同且 asset 缺失：补传缺失 asset 并完成发布。
- checksum 相同且 Release 已完整：保持不可变并提示版本已经发布，同时重试索引写入。
- checksum 不同：拒绝覆盖，修改 `skill.yaml` 版本后重新发布。

不要手工替换已发布 Release 中的 tarball。

## 索引重建

按一个 Skill 重建：

```text
skillctl rebuild-index <namespace>/<name>
```

扫描服务账号可见的所有仓库：

```text
skillctl rebuild-index --all
```

命令从 Forgejo `.artifact.json` 读取 manifest 和 checksum，只向 Skillify DM8 表执行 ORM upsert。输出 `repositories/indexed/skipped/failed`，任何 failed 都需要查看 Forgejo asset 是否缺失或格式损坏。

## namespace 修复

仅当第一次 Web 上传失败并确认没有有效发布时使用：

```text
skillctl release-namespace <namespace> --owner <current-owner> --yes
```

命令要求 namespace 和现有 owner 同时匹配，避免误删其他占用。操作后重新上传并记录处理原因。

## 应用回退

1. 停止新上传和 webhook 投递。
2. 保留当前 DM8、Forgejo 和 devpi 备份。
3. 回退到上一版相同镜像集合，不单独回退某一个 Python 服务。
4. 本阶段没有 Alembic，DM8 schema 由固定初始化 SQL 管理；若未来发生 schema 变化，必须另行提供前滚/回退脚本。
5. 启动后检查 `/healthz`、登录、列表、详情、Release 下载和一个已安装 Skill 的更新。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| Forgejo 有 Release，页面没有 Skill | 执行单仓库索引重建 |
| draft Release 只有部分 asset | 用完全相同源码和版本重新发布 |
| 同版本提示 checksum 冲突 | 不覆盖，提升版本 |
| namespace 被错误占用 | 核对 owner 和 Forgejo 发布后执行释放命令 |
| DM8 表不存在 | 停止服务并导入 `infra/dm8-init/01-skillify-schema.sql` |
| Python 依赖安装失败 | 检查 devpi index、目标包和离线 wheel |
