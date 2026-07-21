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
| `SKILLIFY_BUILD_TTL_SECONDS` | 创建、转换和确认所用临时 build/scan 有效期，默认 86400 秒 | 可选 |

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

`GET /api/skills` 与 `GET /api/search` 共用分页响应结构。每个 `items` 条目直接包含
列表卡片所需的安装、评分和收藏聚合数据，前端无需再逐条请求 Skill 详情：

```json
{
  "items": [
    {
      "namespace": "demo",
      "name": "hello-skill",
      "version": "1.0.0",
      "description": "Say hello.",
      "author": "jane",
      "tags": ["example"],
      "publishedAt": "2026-07-13T10:00:00Z",
      "installCount": 12,
      "ratingAverage": 4.5,
      "ratingCount": 2,
      "starCount": 6
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 20
}
```

- `installCount`：累计成功上报的 `install` 事件数，是平台安装量，不是 Forgejo 资源文件的原始下载次数。
- `ratingAverage`：当前平均评分；尚无人评分时为 `null`。
- `ratingCount`：参与评分的用户数。
- `starCount`：收藏（star）用户数；当前模型中的 star 表示收藏，不是独立的“点赞”模型。

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

### Skill 创建、导入、预览与发布

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/skills/upload` | 上传 Skillify 标准 zip，生成 Native 预览，不立即发布 |
| POST | `/api/skill-builds/guided` | 使用 manifest 字段和 `SKILL.md` 创建引导式 build |
| GET | `/api/skill-builds/{build_id}` | 读取当前完整预览 |
| PATCH | `/api/skill-builds/{build_id}` | 按 revision 更新 manifest 字段或 `SKILL.md` |
| POST | `/api/skill-builds/{build_id}/files` | 上传脚本、资源或其他附属文件 |
| DELETE | `/api/skill-builds/{build_id}/files` | 删除附属文件 |
| POST | `/api/external-skill-scans` | 扫描外部 Agent Skill zip，列出全部 `SKILL.md` 候选 |
| POST | `/api/external-skill-scans/{scan_id}/selections` | 选择一个或多个外部 Skill，并分别转换为 Native build |
| POST | `/api/skill-builds/{build_id}/publish` | 确认指定 revision，并通过唯一正式发布链路发布 |
> 兼容性变更：`POST /api/skills/upload` 已由“上传即发布”改为“上传并生成预览”。
> 所有入口都必须在展示完整转换结果后调用统一的 `/publish` 接口，不能绕过确认直接发布。

所有 build 和 scan 都属于当前 Keycloak 用户，不提供列表接口，也不是草稿箱。默认在创建
24 小时后失效，且不保证跨服务重启恢复；缓存清理或到期后访问返回 `404`。不同用户访问
同一个 ID 也返回 `404`，不泄露临时对象是否存在。

#### 统一 Build 预览结构

标准 zip、引导式创建和外部转换最终都返回相同的预览结构：

```json
{
  "buildId": "4d514b2adf5d4f8aa22167a6a6a98100",
  "sourceType": "guided",
  "revision": 2,
  "status": "ready",
  "expiresAt": "2026-07-13T10:00:00Z",
  "manifest": {
    "manifestVersion": 1,
    "namespace": "demo",
    "name": "hello-skill",
    "version": "1.0.0",
    "description": "Say hello.",
    "author": "jane",
    "license": "MIT",
    "runtime": "claude-agent-skill",
    "targets": ["claude"],
    "dependencies": {"python": [], "system": [], "skills": []},
    "entrypoints": {},
    "permissions": [],
    "tags": ["example"],
    "orchestration": {},
    "reporting": {"enabled": false}
  },
  "manifestYaml": "manifestVersion: 1\nnamespace: demo\nname: hello-skill\nversion: 1.0.0\ndescription: Say hello.\nauthor: jane\nlicense: MIT\nruntime: claude-agent-skill\ntargets:\n- claude\ndependencies:\n  python: []\n  system: []\n  skills: []\nentrypoints: {}\npermissions: []\ntags:\n- example\norchestration: {}\nreporting:\n  enabled: false\n",
  "skillMd": "---\nname: hello-skill\ndescription: Say hello.\n---\n\n# Hello\n",
  "tree": [
    {"path": "SKILL.md", "type": "file", "size": 72},
    {"path": "scripts", "type": "directory", "size": null},
    {"path": "scripts/run.py", "type": "file", "size": 18},
    {"path": "skill.yaml", "type": "file", "size": 320}
  ],
  "detectedFacts": {},
  "missingFields": [],
  "unconfirmedFields": [],
  "issues": [],
  "publishable": true
}
```

- `manifest` 是当前唯一的数据模型，即 `skill.yaml` manifest v1；不存在引导式或外部专用字段。
- `manifestYaml` 是后端将要发布的完整 YAML 预览，不是第二份输入。
- `tree` 是当前将要发布的完整目录树，路径统一使用相对 POSIX 格式。
- `detectedFacts` 只用于说明外部文件中实际检测到的事实，不会隐式写入其他字段。
- `missingFields` 表示仍需填写的字段；`unconfirmedFields` 表示外部来源已有明确值，但用户尚未确认。
- `issues` 保持 `{path, message}` 结构，与现有 validator 一致。
- 只有 `publishable=true` 才能正式发布。
- 每次 PATCH、文件新增或删除都会增加 `revision`。前端必须始终使用最新响应覆盖本地状态。

#### 入口一：Skillify 标准 zip

请求为 `multipart/form-data`，字段名为 `file`：

```http
POST /api/skills/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=@skill.zip
```

zip 根目录或唯一一级包装目录中必须包含 `skill.yaml` 和 `SKILL.md`。接口复用现有上传
大小、解压总大小、文件数、符号链接和路径穿越防护，并执行 Native 校验。成功时返回统一
build 预览，此时不会占用 namespace、创建 Forgejo Release 或写入发布任务。

前端流程：上传 zip → 展示 `manifestYaml`、`skillMd`、`tree` 和 `issues` → 用户确认 →
调用统一发布接口。

#### 入口二：引导式创建

创建接口允许提交不完整内容，因此前端可以在分步骤表单中持续刷新预览：

```http
POST /api/skill-builds/guided
Authorization: Bearer <token>
Content-Type: application/json

{
  "manifest": {
    "namespace": "demo",
    "name": "hello-skill",
    "version": "1.0.0",
    "description": "Say hello.",
    "author": "jane",
    "license": "MIT",
    "runtime": "claude-agent-skill",
    "targets": ["claude"],
    "dependencies": {"python": [], "system": [], "skills": []},
    "permissions": [],
    "tags": ["example"]
  },
  "skillMd": "---\nname: hello-skill\ndescription: Say hello.\n---\n\n# Hello\n"
}
```

表单字段必须直接使用 manifest v1 名称。Skill 类型选择写入 `runtime`，目标平台写入
`targets`，不得在前端发明另一组最终再映射的字段。后端会补充确定性的结构默认值：
`manifestVersion: 1`、空 `entrypoints`/`orchestration`、`reporting.enabled: false`，以及
引导式创建的空依赖、权限和标签集合。

更新接口按字段合并 `manifest`，并可同时替换完整 `SKILL.md`：

```http
PATCH /api/skill-builds/4d514b2adf5d4f8aa22167a6a6a98100
Authorization: Bearer <token>
Content-Type: application/json

{
  "expectedRevision": 2,
  "manifest": {"tags": ["example", "productivity"]},
  "skillMd": "---\nname: hello-skill\ndescription: Say hello.\n---\n\n# Updated\n"
}
```

上传附属文件：

```http
POST /api/skill-builds/{build_id}/files
Authorization: Bearer <token>
Content-Type: multipart/form-data

path=scripts/run.py
expectedRevision=3
file=@run.py
```

删除附属文件：

```http
DELETE /api/skill-builds/{build_id}/files?path=scripts%2Frun.py&expectedRevision=4
Authorization: Bearer <token>
```

`path` 必须是安全的相对 POSIX 路径。禁止绝对路径、`..`、反斜杠、盘符和路径穿越；
`skill.yaml` 与 `SKILL.md` 是保留路径，只能通过结构化创建/PATCH 接口修改。文件和 build
总大小继续受上传配置限制。

前端建议步骤：选择 `runtime` → 填写 manifest 基础字段 → 编辑 `SKILL.md` → 上传可选
脚本 → 填写并确认依赖/权限/标签 → 上传可选资源 → 展示完整预览 → 用户确认发布。

#### 入口三：外部 Agent Skill zip

扫描请求：

```http
POST /api/external-skill-scans
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=@third-party-skills.zip
```

扫描器递归查找所有名称严格为 `SKILL.md` 的文件。没有候选返回 `422`；多个候选正常返回：

```json
{
  "scanId": "8de4ba8d22884618823864f24bd4b414",
  "expiresAt": "2026-07-13T10:00:00Z",
  "candidates": [
    {
      "candidateId": "fbf35cf51e8c4321ae93e837298d2c33",
      "rootPath": "skills/alpha",
      "frontmatter": {"name": "alpha", "description": "Alpha skill."},
      "detectedPaths": ["requirements.txt", "scripts"],
      "pythonRequirements": ["requests>=2.31"],
      "issues": []
    }
  ]
}
```

选择一个或多个候选：

```http
POST /api/external-skill-scans/8de4ba8d22884618823864f24bd4b414/selections
Authorization: Bearer <token>
Content-Type: application/json

{
  "candidateIds": [
    "fbf35cf51e8c4321ae93e837298d2c33",
    "23f049110f864432aa6e9234d26818be"
  ]
}
```

响应为 `{"builds": [BuildPreview, ...]}`。每个候选创建独立 build，可分别补充、确认和
发布；重复或不属于该 scan 的 candidate ID 返回 `400`。

外部转换严格执行“不猜测”规则：

- 只读取合法 `SKILL.md` frontmatter 中明确声明的 `name`、`description`。
- 只读取 `requirements.txt` 和 `pyproject.toml` 的 `project.dependencies` 中明确声明的
  Python 依赖，不执行构建后端或外部代码。
- 只报告 `scripts`、`assets`、`references`、`resources`、`examples`、
  `requirements.txt`、`pyproject.toml` 和 `package.json` 是否存在。
- 不从 zip 名、目录名、仓库名或脚本内容生成 namespace/name，不自动 slugify 非法名称。
- 不推断 version、author、license、runtime、targets、permissions 或 tags。
- 不把 `package.json` 依赖映射成 Python、system 或 Skill 依赖，也不扫描脚本猜测权限。

外部 build 发布前，用户必须通过 PATCH 明确提交或确认以下字段：
`namespace`、`name`、`version`、`description`、`author`、`license`、`runtime`、
`targets`、`dependencies`、`permissions`、`tags`。即使后三项为空，也必须显式提交空对象或
空数组。检测值存在但尚未由用户提交时出现在 `unconfirmedFields`；完全不存在时出现在
`missingFields`。用户提交后，后端生成 Skillify Native `skill.yaml`，前端必须再次展示
完整 manifest 和目录树，再进行最终确认。

Git 地址导入本次未实现；后续可以增加新的 source adapter，但仍必须输出同一 Native
build 并走相同确认发布接口。

#### 统一最终确认与发布

```http
POST /api/skill-builds/{build_id}/publish
Authorization: Bearer <token>
Content-Type: application/json

{"expectedRevision": 5, "confirmed": true}
```

成功响应：

```json
{
  "buildId": "4d514b2adf5d4f8aa22167a6a6a98100",
  "revision": 5,
  "namespace": "demo",
  "name": "hello-skill",
  "version": "1.0.0",
  "releaseUrl": "http://forgejo/demo/hello-skill/releases/tag/v1.0.0",
  "indexError": null
}
```

该接口按顺序检查用户归属、有效期、`confirmed=true`、最新 revision、转换字段确认状态和
完整目录校验，然后原子标记发布状态。正式发布统一执行 namespace 所有权校验、可选 Git
源码提交、打包、checksum、Forgejo Release、索引和发布任务记录。成功发布的 build 不再
允许修改或重复确认；发布失败会恢复为可重试状态，前端可使用同一 build/revision 重试。

## Endpoint Code Map（个人非商业）

人用 Code Map 使用固定的 GitNexus v1.6.9，只在 Endpoint 本机扫描 Skillify 状态目录中的
工作区快照，并通过本机 Chrome 打开。它不替换 Agent CodeGraph，也不把图谱、源码或
localhost URL 返回中央 Web。

该功能受 PolyForm Noncommercial 1.0.0 约束，仅允许个人开发、研究、实验和无预期商业
应用；许可证没有按天到期的试用期限。如果项目用途转为商业应用，必须停用该功能，直到
取得适用商业授权或更换引擎。

Endpoint 配置固定 manifest 和已构建的 GitNexus runtime：

```bash
export SKILLIFY_GITNEXUS_MANIFEST=/opt/skillify/offline/codemap/gitnexus-visualizer-manifest.json
export SKILLIFY_GITNEXUS_ROOT=/opt/skillify/codemap/gitnexus/1.6.9

skillctl codemap visualize doctor
skillctl codemap visualize start --workspace <alias>
skillctl codemap visualize status --workspace <alias>
skillctl codemap visualize open --workspace <alias>
skillctl codemap visualize stop --workspace <alias>
```

源码归档和离线 runtime 构建入口见
`infra/offline/gitnexus-visualizer-manifest.json` 与
`scripts/build-gitnexus-visualizer-artifact.sh`。最终 Linux 构件 SHA256、Chrome 最低版本、
强制断网和完整 Endpoint 链路必须在测试环境验收。

常见错误：

| HTTP | 场景 |
| --- | --- |
| `400` | 非 zip、危险文件路径、非法或重复 candidate ID、zip 安全检查失败 |
| `401` | 缺少或无效 Keycloak Bearer token |
| `404` | build/scan 不存在、已过期或属于其他用户 |
| `409` | revision 已过期、build 正在/已经发布、版本已存在 |
| `413` | 原始上传或附属文件超过配置限制 |
| `422` | Native 校验失败、没有 `SKILL.md` 候选、字段未补齐/未确认、`confirmed` 非 true |
| `502` | Forgejo 调用失败 |
| `503` | index 或发布配置缺失 |

当 `confirmed=true` 但 build 尚未达到可发布状态时，`422` 的 `detail` 为结构化对象，前端
应直接刷新补全/确认界面：

```json
{
  "detail": {
    "message": "build is not ready to publish",
    "missingFields": ["namespace", "version", "permissions", "tags"],
    "unconfirmedFields": ["name", "description", "dependencies"],
    "issues": [{"path": "skill.yaml:$", "message": "'namespace' is a required property"}]
  }
}
```

revision 冲突的 `detail` 包含 `currentRevision`。前端收到 `409` 后应重新 GET 当前预览，
不得自动用旧内容覆盖。正式发布同一 namespace/name/version 的重试会更新当前用户自己的
发布任务；不同用户的记录和临时 build 相互隔离。

本次只实现后端，`web/` 现有上传页面尚未迁移到 preview/confirm 契约。前端需要按本节
三个入口的时序改造，不能继续把 `/api/skills/upload` 的成功响应当作已发布结果。

### 个人工作台

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/my/skills` | 当前用户名下的最新 Skill |
| GET | `/api/my/namespaces` | 当前用户拥有的 namespace |
| GET | `/api/my/publish-jobs?status=failed|all` | 当前用户的发布结果和失败原因 |
| GET | `/api/my/usage` | Skill 数量、安装总数和逐 Skill 使用量 |
| GET | `/api/my/subscriptions` | 当前用户订阅的 Skill 及最新版本 |

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
| 创建/导入 Skill | 前端待接入本节 preview/confirm API；支持标准 zip、引导式创建和外部转换 |
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
## 构件检查边界

正式构件必须使用固定语义版本、可追溯的内网来源与 SHA256。发布同时生成自研
CycloneDX 1.5 SBOM，并执行内建 block/warn 规则。该检查不包含完整 CVE 漏洞库，
不代表企业级供应链安全认证；当前也不接入 Syft、Grype 或 Cosign。
