# 测试服务器部署记录

- 时间：2026-07-13（Asia/Shanghai）
- 源提交：`7ec519ce39c0d3f0fb7680b92bd5002baf5ea1d5`
- 目录：`/opt/skillify-test/app`
- 拓扑：Nginx/frontend → FastAPI；Forgejo → PostgreSQL；Skillify → 外部 DM8；Keycloak、Rbac.Api 为外部服务；devpi 独立 volume。
- 入口：前端/API `:18090`，Forgejo `:3000`，devpi `:3141`，webhook `:18089`。

目标机为 CentOS 7、Linux 3.10、Docker 23.0.6、Compose 2.27.1。由于 8080、18088、5432 已被既有业务占用，采用上述不冲突端口。`postgres:16-alpine` 在该 3.10 内核初始化时报写入 `postmaster.pid`/WAL 的 `Operation not permitted`；仅在测试服务器 override 为 PostgreSQL 12，初始化及重启均健康。未触碰既有容器或数据。

部署沿用 `infra/docker-compose.yml`。测试环境 `.env` 权限为 0600，密码/token 未写入 Git。额外配置 `SKILLIFY_FORGEJO_ORG=skillify`，并创建固定 Forgejo 组织和服务账号。Keycloak 新建 `skillify` realm、`skillify-web` public client、audience mapper 和两名测试用户。

启动/检查命令：

```sh
cd /opt/skillify-test
./start-test-server-docker.sh
```

The test server must be started with Docker CLI in dependency order. Do not use
`docker compose up` on this CentOS 7 host: recreating the database without the
server-specific PostgreSQL 12 image makes its existing data directory incompatible.
Keycloak, Rbac.Api and Skillify all use the `master` realm and its `skillify-web`
public client.

全栈 `restart` 后 6 个服务恢复；API 与 webhook `/healthz` 均为 200，devpi volume 中测试包仍可安装。

