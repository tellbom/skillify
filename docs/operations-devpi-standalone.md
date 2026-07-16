# 独立 devpi 运维

devpi 是独立的 Python Package Infrastructure。Skillify 只通过标准 PyPI index URL 使用它，不负责 devpi 的账号、index、备份或升级生命周期。

## 启停

```bash
docker compose -f infra/devpi/docker-compose.yml up -d
docker compose -f infra/devpi/docker-compose.yml down
```

Skillify 继续通过 `SKILLIFY_DEVPI_INDEX_URL` 指向该服务或其他已部署的 devpi。主 Skillify Compose 不依赖此容器启动。

## 备份

1. 停止向 devpi 写入并记录 `devpi-server` 版本。
2. 使用当前版本支持的导出命令；若采用 volume 备份，停止独立栈后归档 `skillify-devpi_devpi-data`。
3. 记录 index 配置、备份文件 SHA256 和时间点。

## 恢复

1. 使用相同 devpi 版本创建空数据目录。
2. 恢复导出数据或 volume 归档。
3. 启动独立栈并验证目标 `/+simple/` index。
4. 在隔离 venv 中安装一个已缓存包，再安装一个包含 Python 依赖的 Skill。

## 升级

升级前完成备份和隔离恢复演练。更新 `infra/devpi/Dockerfile` 中的固定版本后，重建独立栈并重复恢复与安装验证；Skillify 主栈不需要随 devpi 同步升级。
