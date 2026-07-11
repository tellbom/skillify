# Skillify

Skillify 是面向内网的 Skills 管理与使用平台，提供 Skill 校验、打包、版本发布、
搜索、安装、排行榜、评论、评分、收藏、订阅和个人工作台。项目由以下部分组成：

- `skillify-web`：FastAPI 业务后端，默认监听 `8089`。
- `skillify-webhook`：接收 Forgejo tag push，默认监听 `8088`。
- `web/`：Vue 3 + Vite 前端，生产环境由 Nginx 提供服务。
- `skillctl`：Skill 创建、校验、发布、安装和维护 CLI。
- Forgejo：保存 Skill 源码、commit、tag、Release 和发布资产。
- DM8：保存 Skillify 索引、评论、评分、事件、namespace 归属等业务数据。
- devpi：为 Skill 运行环境提供 Python 包索引。
- Keycloak + Rbac.Api：分别负责登录身份和前端菜单/按钮权限。

## 数据边界

Forgejo 和 Skillify 的数据相互隔离：

| 组件 | 保存内容 |
| --- | --- |
| Forgejo PostgreSQL | 仅保存 Forgejo 自身数据 |
| Forgejo Git/Release | Skill 源码、提交、版本 tag、Release、压缩包和校验文件 |
| Skillify DM8 | Skill 索引、评论、评分、收藏、订阅、事件、namespace owner、发布任务 |
| devpi | Python 包和索引 |

Skillify 不直接读写 Forgejo PostgreSQL。生产环境不会通过 SQLAlchemy 自动创建或修改
DM8 表，DM8 结构以 `infra/dm8-init/` 下的 SQL 文件为事实源。

## 环境要求

- Python `>=3.10`
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ 和 npm（前端开发）
- DM8 数据库及 `DIsql`（正式业务库）
- Docker 与 Docker Compose（完整环境部署）
- 可访问的 Forgejo、Keycloak、Rbac.Api；devpi 可由 Compose 启动

## 后端本地启动

### 1. 安装依赖

```powershell
cd E:\skillify
uv sync --frozen
```

### 2. 初始化 DM8

使用 Skillify 专用 DM8 用户/schema，按文件名顺序执行：

```text
infra/dm8-init/01-skillify-schema.sql
infra/dm8-init/02-c1-version-center.sql
infra/dm8-init/03-c2-my-skills.sql
infra/dm8-init/04-c5-community.sql
infra/dm8-init/05-c4-search-indexes.sql
```

示例命令以目标 DM8 安装版本的 `DIsql` 参数为准。不要把账号、密码或服务器地址提交到
Git。项目没有历史生产数据负担，上述脚本用于从空 schema 构建当前完整结构。

### 3. 配置环境变量

PowerShell 示例：

```powershell
$env:SKILLIFY_INDEX_DB_URL='dm+dmPython://SKILLIFY_USER:URL_ENCODED_PASSWORD@dm8-host:5236'
$env:SKILLIFY_FORGEJO_URL='http://forgejo-host:3000'
$env:SKILLIFY_FORGEJO_TOKEN='<forgejo-token>'
$env:SKILLIFY_KEYCLOAK_REALM_URL='http://keycloak-host/realms/internal'
$env:SKILLIFY_KEYCLOAK_AUDIENCE='skillify-web'
$env:SKILLIFY_WEB_BASE_URL='http://127.0.0.1:8089'
```

主要后端变量：

| 变量 | 用途 | 必需性 |
| --- | --- | --- |
| `SKILLIFY_INDEX_DB_URL` | Skillify DM8 SQLAlchemy URL | 业务 API 必需 |
| `SKILLIFY_FORGEJO_URL` | Forgejo 服务地址 | 详情源码、发布、diff 必需 |
| `SKILLIFY_FORGEJO_TOKEN` | Forgejo 服务账号 token | Forgejo 操作必需 |
| `SKILLIFY_FORGEJO_ORG` | 固定 Forgejo org；未配置时使用 namespace | 可选 |
| `SKILLIFY_KEYCLOAK_REALM_URL` | JWT issuer/realm 地址 | 除健康检查外的 API 必需 |
| `SKILLIFY_KEYCLOAK_AUDIENCE` | JWT `aud` 期望值 | 推荐配置 |
| `SKILLIFY_WEBHOOK_SECRET` | Forgejo Webhook HMAC secret | Webhook 推荐配置 |
| `SKILLIFY_WEB_BASE_URL` | Agent 安装提示中的 Web API 地址 | 可选 |
| `SKILLIFY_WEB_UPLOAD_GIT_ENABLED` | Web 上传时提交源码并创建 tag | 完整部署设为 `true` |
| `SKILLIFY_MAX_UPLOAD_BYTES` | 上传 zip 最大字节数，默认 20 MiB | 可选 |
| `SKILLIFY_MAX_EXTRACTED_BYTES` | 解压后最大总字节数，默认 100 MiB | 可选 |
| `SKILLIFY_MAX_EXTRACTED_FILES` | 解压后最大文件数，默认 5000 | 可选 |

也可以在 `~/.skillify/config.yaml` 中使用对应的小写配置项；环境变量优先于配置文件。

### 4. 启动业务 API

```powershell
uv run skillify-web
```

启动后：

- 健康检查：`http://127.0.0.1:8089/healthz`
- Swagger UI：`http://127.0.0.1:8089/docs`
- ReDoc：`http://127.0.0.1:8089/redoc`
- OpenAPI JSON：`http://127.0.0.1:8089/openapi.json`

也可以直接使用 Uvicorn，并在开发时启用自动重载：

```powershell
uv run uvicorn skillify.web.app:app --host 0.0.0.0 --port 8089 --reload
```

### 5. 启动 Forgejo Webhook

```powershell
$env:SKILLIFY_WEBHOOK_SECRET='<与 Forgejo Webhook 配置一致的 secret>'
uv run skillify-webhook
```

- 健康检查：`http://127.0.0.1:8088/healthz`
- 接收地址：`POST http://127.0.0.1:8088/webhook/forgejo`

Webhook 只处理 push 事件中的版本 tag；匹配成功后下载源码、校验、打包、创建或恢复
Forgejo Release，并更新 DM8 派生索引。

## 前端本地启动

```powershell
cd E:\skillify\web
npm ci
$env:VITE_KEYCLOAK_REALM_URL='http://keycloak-host/realms/internal'
$env:VITE_KEYCLOAK_CLIENT_ID='skillify-web'
$env:VITE_RBAC_BASE_URL='http://rbac-host:18085'
$env:VITE_RBAC_PROJECT='skillify'
npm run dev
```

Vite 默认将 `/api` 代理到 `http://127.0.0.1:8089`，将开发环境的 `/rbacServer`
代理到 `VITE_RBAC_BASE_URL`。业务页面不是硬编码路由，而是根据 Rbac.Api
`/api/admin/index` 返回的菜单动态注册，因此 Rbac.Api 必须配置对应的 route path、
component 和 ruleCode。

## Docker Compose 启动

完整环境包含 Forgejo PostgreSQL、Forgejo、devpi、Webhook、业务后端和前端 Nginx。
DM8、Keycloak 和 Rbac.Api 为外部服务。

```powershell
cd E:\skillify\infra
Copy-Item .env.example .env
# 编辑 .env，至少配置 DM8、Forgejo token、Webhook secret、Keycloak 和 Rbac.Api
docker compose up -d --build
docker compose ps
```

默认入口：

| 服务 | 地址 |
| --- | --- |
| Skillify 完整界面 | `http://localhost:8080` |
| Skillify Swagger | `http://localhost:8080/docs` |
| Skillify 健康检查 | `http://localhost:8080/healthz` |
| Forgejo | `http://localhost:3000` |
| Forgejo Webhook | `http://localhost:8088/webhook/forgejo` |
| devpi | `http://localhost:3141` |

生产 Nginx 将 `/api`、`/docs`、`/redoc`、`/openapi.json` 和 `/healthz` 转发到
`skillify-web:8089`，其他路径按 Vue SPA 处理。

## API 认证

- `GET /healthz` 不需要登录。
- `/api/*` 均要求有效 Keycloak Bearer JWT，包括读取接口。
- 请求头格式：`Authorization: Bearer <access-token>`。
- Webhook 使用 `X-Forgejo-Signature` 或 `X-Gitea-Signature` 验证 HMAC。
- yank/unyank 还要求当前用户是版本作者或 namespace owner。
- 评论删除要求当前用户是评论作者或对应 namespace owner。
- namespace 采用首次 Web 上传者占用的规则，后续上传者必须匹配 owner。

具体请求字段、响应字段和在线调试以 Swagger/ReDoc 为准。

## 业务 API

### Skill 检索与详情

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/skills` | 分页列出 Skill；支持 namespace、author、tags、sort |
| GET | `/api/search` | 按名称/描述搜索并分页、筛选、排序 |
| GET | `/api/skills/{namespace}/{name}` | Skill 详情；可用 `version` 指定历史版本 |
| GET | `/api/skills/{namespace}/{name}/install` | 获取 CLI 安装命令和 Agent 安装提示 |
| GET | `/api/skills/{namespace}/{name}/orchestration` | 获取 Skill orchestration 元数据 |

检索参数：

- `q`：名称/描述关键字。
- `namespace`、`author`：精确过滤。
- `tags`：逗号分隔，按全部标签匹配。
- `sort`：`updated`、`installs` 或 `rating`。
- `page`：从 1 开始；`pageSize`：1 至 100。

### 版本中心

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/skills/{namespace}/{name}/versions` | 版本时间线、发布时间、yank 状态和 Release notes |
| GET | `/api/skills/{namespace}/{name}/diff?from=x&to=y` | 比较两个 Forgejo tag 的文件变化 |
| POST | `/api/skills/{namespace}/{name}/versions/{version}/yank` | 撤回默认推荐版本，但保留显式安装能力 |
| POST | `/api/skills/{namespace}/{name}/versions/{version}/unyank` | 恢复被撤回版本 |

### 社区与统计

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST/DELETE | `/api/skills/{namespace}/{name}/star` | 收藏/取消收藏并返回收藏数 |
| POST/DELETE | `/api/skills/{namespace}/{name}/subscription` | 订阅/取消订阅新版本 |
| GET | `/api/skills/{namespace}/{name}/comments` | 读取评论和回复树数据 |
| POST | `/api/skills/{namespace}/{name}/comments` | 新增评论；`parentId` 表示回复 |
| DELETE | `/api/skills/{namespace}/{name}/comments/{comment_id}` | 软删除评论 |
| POST | `/api/skills/{namespace}/{name}/rating` | 提交或更新 1 至 5 分评分 |
| POST | `/api/skills/{namespace}/{name}/events` | 上报 `install` 或 `run` 事件 |
| GET | `/api/leaderboard` | 排行榜，dimension 支持 installs/rating/recent |

排行榜 `window` 支持 `week`、`month`、`all`；时间窗口主要作用于安装事件统计。

### 上传与个人工作台

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/skills/upload` | 上传 Skill zip，校验后提交 Forgejo Git/Release 并写入索引 |
| GET | `/api/my/skills` | 当前用户名下的最新 Skill |
| GET | `/api/my/namespaces` | 当前用户拥有的 namespace |
| GET | `/api/my/publish-jobs?status=failed|all` | 当前用户的发布结果和失败原因 |
| GET | `/api/my/usage` | Skill 数量、安装总数和逐 Skill 使用量 |
| GET | `/api/my/subscriptions` | 当前用户订阅的 Skill 及最新版本 |

上传文件必须是 `.zip`，根目录或唯一子目录中需要包含 `skill.yaml` 和 `SKILL.md`。
同一用户重试相同 namespace/name/version 会更新自己的发布任务；不同用户的记录相互隔离。

## Webhook API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/healthz` | Webhook 服务健康检查 |
| POST | `/webhook/forgejo` | 接收 Forgejo/Gitea push webhook |

Forgejo 配置建议：

- Target URL：容器内使用 `http://webhook:8088/webhook/forgejo`。
- Trigger：Push events。
- Secret：与 `SKILLIFY_WEBHOOK_SECRET` 一致。
- Skill tag：建议使用与 `skill.yaml` 版本一致的 `v<version>`。

## 前端界面用途

| 页面 | 用途 |
| --- | --- |
| 登录页 | 初始化 Keycloak 会话，并桥接 Rbac.Api 用户与菜单信息 |
| Skill 列表/搜索 | 浏览、搜索、按 namespace/作者/标签筛选，按更新时间/安装量/评分排序 |
| Skill 详情 | 阅读 README/SKILL.md、复制安装命令、下载资产、评分、收藏和订阅 |
| 版本中心 | 查看版本时间线、Release notes、切换历史版本、diff、yank/unyank |
| 评论区 | 发布评论、回复、查看软删除占位、删除本人有权限的评论 |
| 排行榜 | 按安装量、评分或最近发布排序，并切换周/月/全部时间窗口 |
| 上传 Skill | 上传 zip，展示校验错误、发布结果和 Forgejo Release 地址 |
| 我的 Skill | 查看本人 Skill、namespace、使用统计、发布结果和失败重试入口 |
| RBAC 管理 | 管理管理员、用户组、规则、API 映射和项目授权 |

业务页面的最终 URL 和可见性取决于 Rbac.Api 下发的菜单。静态保留页面只有登录、
401、403、404 和根布局；若菜单中的 component 无法映射到 `web/src/views/**/*.vue`，
动态路由不会正常注册。

## CLI

```powershell
uv run skillctl --help
uv run skillctl init <namespace>/<name> --dest <parent-directory>
uv run skillctl validate <skill-directory>
uv run skillctl publish <skill-directory>
uv run skillctl install <namespace>/<name>
uv run skillctl install <namespace>/<name>@<version>
uv run skillctl search <keyword>
uv run skillctl list
uv run skillctl update <namespace>/<name>
uv run skillctl remove <namespace>/<name>
uv run skillctl rebuild-index --all
```

本地状态默认保存在 `~/.skillify/`，包括配置、已安装 Skills、虚拟环境、Agent 投影、
锁文件和缓存。

## 开发验证

```powershell
uv sync --frozen
uv run pytest -q
uv run python -m compileall -q src

cd web
npm test
npm run type-check
npm run build
```

更详细的部署、恢复和试用材料：

- [基础设施说明](infra/README.md)
- [DM8、Forgejo、devpi 运维](docs/operations-dm8-forgejo-devpi.md)
- [发布恢复](docs/operations-release-recovery.md)
- [内网试用清单](docs/internal-pilot-checklist.md)
- [Skill manifest v1](spec/skill-manifest-v1.md)
