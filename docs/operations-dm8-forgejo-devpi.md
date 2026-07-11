# Skillify 数据备份与恢复

本文覆盖三套彼此独立的数据：Skillify DM8 业务 schema、Forgejo PostgreSQL + `/data`、devpi `/data`。所有命令中的主机、用户、目录和文件名都是占位符。

## 一致性原则

- Skillify 不直接备份或修改 Forgejo PostgreSQL 表。
- Forgejo 数据库与 Forgejo `/data` 必须在同一维护窗口生成一致性备份。
- DM8 只备份 Skillify 专用用户/schema 下的五张业务表。
- 恢复演练先在隔离实例执行，核对后再安排正式恢复。
- 凭据通过运维平台、交互提示或临时环境变量提供，不写入仓库和长期脚本。

## DM8

### 备份

在安装了 DM8 客户端工具的主机上，按当前版本的 `dexp` 语法导出 Skillify schema：

```text
dexp USERID=<skillify-user>/<password>@<dm8-host>:<port> \
  SCHEMAS=<skillify-schema> DIRECTORY=<backup-directory> \
  FILE=skillify-<timestamp>.dmp LOG=skillify-<timestamp>-export.log
```

检查导出日志无失败，并记录 DM8 版本、schema、导出文件 checksum 和时间点。

### 恢复

1. 在隔离 DM8 实例创建空的 Skillify 专用用户/schema。
2. 使用匹配版本的 `dimp` 导入：

```text
dimp USERID=<target-user>/<password>@<target-host>:<port> \
  DIRECTORY=<backup-directory> FILE=skillify-<timestamp>.dmp \
  LOG=skillify-<timestamp>-import.log
```

3. 用 DIsql 核对五张表存在，唯一约束和索引存在。
4. 分别统计 `skill_index`、`skill_comments`、`skill_ratings`、`skill_events`、`skill_namespace_owners` 行数。
5. 启动 `skillify-web`，验证列表、详情、评论、评分和排行榜读取。

`dexp/dimp` 参数会随安装版本和目录授权方式变化，以目标 DM8 自带手册为准。

## Forgejo

### 备份

1. 停止 `frontend`、`skillify-web`、`webhook` 和 `forgejo`，保留 PostgreSQL 运行。
2. 从 PostgreSQL 容器执行逻辑备份：

```text
docker compose exec -T db pg_dump -U <forgejo-db-user> \
  --format=custom --file=/tmp/forgejo.dump <forgejo-db-name>
docker compose cp db:/tmp/forgejo.dump <backup-directory>/forgejo-<timestamp>.dump
```

3. 备份 `forgejo-data` volume。可使用企业备份平台，或在停止 Forgejo 后用一次性容器只读挂载并归档。
4. 分别记录数据库 dump 和数据归档 checksum。

### 恢复

1. 创建空 Forgejo PostgreSQL 数据库和空 `forgejo-data` volume。
2. 恢复 `/data` 归档，再使用 `pg_restore` 恢复数据库。
3. 按原版本启动 Forgejo，验证登录、组织、仓库、tag、Release 和 asset 下载。
4. 启动 Skillify 后执行 `skillctl rebuild-index --all`，确认 DM8 派生索引与 Forgejo Release 一致。

不要只恢复 Forgejo PostgreSQL 而复用另一个时间点的 `/data`。

## devpi

### 备份

优先使用 devpi-server 对应版本支持的导出方式。若采用 volume 备份：

1. 停止依赖安装流量和 `devpi` 服务。
2. 归档 `devpi-data` volume。
3. 记录 devpi-server 版本、索引配置、归档 checksum 和时间点。

### 恢复

1. 使用相同 devpi-server 版本创建空数据目录。
2. 恢复导出数据或 volume 归档。
3. 启动 devpi，验证目标 index 可列出。
4. 从隔离 venv 安装一个已缓存包，再安装一个带 Python 依赖的 Skill。

## 演练记录

每次演练记录：备份开始/结束、恢复开始/结束、操作者、软件版本、文件 checksum、五表行数、Forgejo 仓库/Release 数量、devpi 验证包和最终结论。
