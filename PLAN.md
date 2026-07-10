# Skillify — 内网私有化 Skills 社区 · 架构方案

> 状态：设计评审稿（Opus 4.8 起草，待 GPT5.5 + 用户共同评审）
> 目标：内网私有化的 Skills 社区，对标 skillsmp.com。开放式共享，无沙箱评审、无聊天系统；保留评论 + 排行榜作为附属功能。
> 交付对象：Sonnet 5 开发。

---

## 0. 已确认的关键决策

| 决策点 | 结论 |
| --- | --- |
| Skill 类型 | **兼容两者**：MVP 先做 Claude Agent Skills（SKILL.md），manifest 预留自定义 / agent 编排扩展字段 |
| 分发方式 | 底层统一走**不可变构件**（tarball + checksum + manifest），上层提供两个入口：① `skillctl` CLI ② agent 自拉取 prompt（skillsmp 模式） |
| 安装目录 | **中立目录 `~/.skillify/skills/`** 为真相源，再按 `--target` 经适配层同步/软链到具体 agent 目录（不绑定 Claude） |
| 目标平台 | 内网生产：**仅 Linux**（无互联网、私有 LLM 走 OpenAI 兼容协议）。外网开发/测试：Windows + Linux。**内网不需支持 Windows** |
| 主力 Agent | **OpenCode + Claude Code**（首批适配 target），预留 Codex / Aider / 自研 agent / 项目本地 |
| 用户上传 | 支持，但必须通过**标准化格式校验**才能入库 |
| MVP 边界 | CLI + Forgejo + 手写示例 skill + **最小 Web 目录** + **依赖隔离** |
| Python/脚本依赖 | **per-skill venv（uv）+ 内网 PyPI 镜像（devpi）** |

---

## 1. 核心架构判断（地基）

**源 / 构件分离** — 整个系统的地基：
- Git（Forgejo）= 源码 + 版本历史 + 审计日志的唯一真相源。
- 客户端**绝不直接 `git clone` 安装**。链路为：源码 → CI 打包成不可变构件（tarball + 版本号 + checksum + manifest）→ 发布到 Forgejo Release/Package → CLI / agent 从构件安装。
- 好处：可复现、可回滚、有完整日志，是"标准化格式"能真正落地的前提。

**先定 manifest 规范，再写任何安装器** — `skill.yaml` 是所有模块的契约（CLI、Web、依赖隔离、agent 编排、上报都读它）。规范没定死前不写代码。

**CLI 安装器是 MVP 真正核心，不是 Web** — Web 在 MVP 阶段只需"浏览 + 复制安装命令/prompt"。

---

## 2. 组件总览

| 模块 | MVP 选型 | 后期演进 | 说明 |
| --- | --- | --- | --- |
| Git 后端 | **Forgejo** | — | 托管 + Package Registry + OAuth + Webhook + 审计日志 |
| 标准格式 | `skill.yaml` + 目录规范 + 校验器 | manifestVersion 版本化 | 兼容 Claude SKILL.md，预留 agent 字段 |
| CLI 安装器 | **Python + Typer**（`skillctl`） | 有分发/性能诉求再 Go | 与后端同栈，迭代快 |
| 打包/发布 | CI 校验 → 打包 → Release 构件 | — | push 触发 |
| 社区站后端 | **FastAPI** | — | 读 Forgejo + Postgres，聚合索引 |
| 社区站前端 | **Vue3 或 React** | — | 浏览/搜索/文档/复制命令/上传/评论/排行榜 |
| 数据库 | **PostgreSQL** | — | 索引、评论、排行榜、上报事件 |
| 搜索 | **Postgres 全文** | Meilisearch / OpenSearch | 量大再换 |
| 依赖隔离 | **per-skill venv（uv）** | — | 不污染系统 Python |
| Agent 适配层 | **中立目录 + agents/*.yaml**（首批 claude/opencode） | codex/aider/自研/project | Linux 软链，Windows(仅外网测试)复制 |
| Python 镜像 | **devpi** | Forgejo PyPI Registry | devpi 更简单 |
| 包/资源存储 | **Forgejo Release 资产** | MinIO | — |
| 登录 | **Keycloak（前端直连）+ Forgejo 上游接 Keycloak** | ~~Forgejo OAuth~~ | 2026-07-09 用户裁决变更，见下方 §0.1 |
| 文档渲染 | Markdown + Shiki | — | — |
| Agent 通道 | 文档化拉取端点 / MCP（预留） | — | 内网限定 + token 认证 |
| 上报/编排 | 事件上报 API（stub）+ manifest 预留段 | 实装编排 | 本机→服务端报备运行情况 |

> MVP 主动砍掉：Meilisearch、MinIO —— 分别由 Postgres 全文 / Release 资产顶替。Keycloak 原计划
> MVP 不上，M4 阶段由用户裁决改为立即引入，见 §0.1。

### 0.1 登录方案变更（2026-07-09，M4 阶段，用户裁决）

M0-M3 评审通过后，用户在 M4 开工前提出：公司已有 Keycloak + 一套独立的 .NET RBAC 权限中心
（`Rbac.Api`，菜单级权限管理，服务于其他内部系统），希望 Skillify 复用而不是自建。三轮澄清后
落地的方案：

- **Keycloak 定位**：Forgejo 自身的上游身份源指向 Keycloak（Forgejo 侧配置，不涉及 Skillify
  代码），全公司账号统一；**Skillify 前端也直接对接 Keycloak**（Vue3 用 `keycloak-js`，标准
  Authorization Code + PKCE 重定向登录），不经 Skillify 自己的后端中转。
- **RBAC 范围**：明确裁决为**只保护前端界面的路由/菜单可见性**（是否显示"上传"入口），**不**
  用来保护 Skillify 自己的 API——所有 Skillify API 该不该要求登录，统一走 Keycloak JWT 校验
  （FastAPI 侧验签，见 `skillify/web/auth.py`），不接入 RBAC 中间层。
- **RBAC 调用方**：前端直连 `Rbac.Api`（`POST /api/auth/login` 拿授权结果 + `adminInfo`，
  `GET /api/admin/index` 拿裁剪后的菜单树），不经 Skillify 后端代理——用户明确要求"仇 flow/web
  同样模式"（`E:\Web\flow\web` 的 `src\api\backend\rbac\bridge.ts` token-bridge 模式）。
- **真实环境信息缺失**：`Rbac.Api` 和 Keycloak 的真实 realm/client ID/服务地址在开发环境里都
  拿不到（勘察 `E:\router\router` 发现其 checked-out 的 dev 配置走 `TrustedJwt` 模式、零签名
  校验，也没有真实 Keycloak 信任关系配置）。用户裁决：**现在就写代码，全部用环境变量占位**
  （`VITE_KEYCLOAK_REALM_URL`/`VITE_KEYCLOAK_CLIENT_ID`/`VITE_RBAC_BASE_URL`/`VITE_RBAC_PROJECT`
  /`SKILLIFY_KEYCLOAK_REALM_URL`/`SKILLIFY_KEYCLOAK_AUDIENCE`），真实值到位后只改配置不改代码。
- **发布仍走服务账号**：上传发布到 Forgejo 仍使用 Skillify 后端自己的 `forgejo_token`（服务账号），
  未实现"逐用户 Forgejo OAuth token"换取——那是一个独立的、更大的工作量（Keycloak↔Forgejo↔
  Skillify 三方 SSO token 链路），用户的诉求聚焦在 RBAC/菜单集成，未要求做这个。上传者身份通过
  Keycloak `preferred_username` 写入 Release notes 与索引 `author` 字段做归属记录，不是真正的
  "以该用户身份操作 Forgejo"。此简化已在代码注释（`publisher.py`/`upload_service.py`）中标注，
  留作后续评审/追加工作项。

---

## 3. Skill 标准格式

目录结构：
```
my-skill/
  SKILL.md            # Claude Agent Skill 主文件（frontmatter: name, description...）
  skill.yaml          # Skillify manifest（扩展元数据，见下）
  scripts/            # python / shell 脚本
  requirements.txt    # 或 pyproject.toml —— python 依赖
  resources/          # 附带静态资源
  README.md
```

`skill.yaml` 字段：
```yaml
manifestVersion: 1              # spec 版本，向后兼容用
name: my-skill
version: 0.1.0                  # semver
description: ...
author: ...
license: ...
runtime: claude-agent-skill     # claude-agent-skill | custom
targets: [claude, opencode]     # 兼容的 agent；install --target 覆盖；project=项目本地 .skills
dependencies:
  python: ["requests>=2.31"]    # 走内网 devpi
  system: []                    # 声明用到的系统工具
  skills: []                    # skill 间依赖（其他 skill 名@版本）
entrypoints: {}                 # 入口/脚本声明
permissions: []                 # 声明用到的能力（供审阅/安全）
orchestration: {}               # 预留：agent 编排插口
reporting: {enabled: false}     # 预留：本机→服务端上报开关
# checksum 在发布时由 CI 生成写入 Release 元数据，不手写
```

---

## 4. 关键数据流

**发布（publish）**
作者写 skill → `skillctl publish`（或 Web 上传）→ 标准格式校验 → push Forgejo → CI 校验 manifest + 打包 tarball + 生成 checksum → 发布 Release 构件 → 索引写入 Postgres → Web / 搜索可见。

**安装（install）**
用户 `skillctl install X [--target claude|opencode|codex|project]`（或粘贴 agent 自拉取 prompt）→ 解析版本 → 从 Forgejo 下构件 → 校验 checksum → 解压到**中立目录 `~/.skillify/skills/X`（真相源）** → 建 per-skill venv → 从 devpi 装 python 依赖 → 解析 skill 间依赖 → 写本地清单/lock → **按 target 经适配层同步/软链到具体 agent 目录**（未指定则装所有 manifest 声明且本机已装的 agent）→（可选）上报服务端。

**Agent 适配层**
中立目录是唯一真相源，各 agent 目录只是它的投影，避免被任一 agent 绑死。适配规则由 `~/.skillify/agents/<agent>.yaml` 描述（目标目录、链接方式、格式转换）。Linux 用软链（symlink）；外网 Windows 测试环境降级为复制（copy）。首批适配 **claude / opencode**，预留 codex / aider / 自研 / project(项目本地 `.skills`)。

本地目录结构：
```
~/.skillify/
├── skills/                 # 中立真相源：skills/<namespace>/<name>/
│   └── excel/pivot-analysis/
├── venvs/                  # per-skill 隔离环境（uv）
├── agents/                 # 适配规则：目标目录 + 链接/复制 + 格式映射
│   ├── claude.yaml
│   ├── opencode.yaml
│   └── codex.yaml
├── locks/                  # 安装锁 + 版本锁定（可复现）
├── cache/                  # 构件下载缓存
└── config.yaml             # Forgejo/devpi 地址、token、默认 target
```

**Agent 自拉取（skillsmp 模式）**
每个 skill 页面提供一段可粘贴的 prompt/命令，让 Claude Code agent 通过**文档化的内网端点（或 MCP server）** 自行 fetch + 校验 + 安装。安全边界：限内网 + token 认证 + 走同一构件链路。

---

## 5. 里程碑

- **M0 规范与地基**：定 `skill.yaml` spec + 目录标准 + 校验器；docker-compose 起 Forgejo + Postgres + devpi。
- **M1 CLI 闭环**：`skillctl install/publish/list/update/remove` + 打包 + checksum 校验 + venv + devpi 装依赖；手写 2–3 个含 python 依赖的示例 skill 跑通"发布→安装→本机运行"。
- **M2 发布流水线**：Forgejo CI（或 webhook→打包服务）自动打包 + 生成 checksum + 发布 + 索引入库。
- **M3 Web 目录**：FastAPI 后端（聚合 Forgejo + Postgres）+ 前端浏览/搜索/文档渲染/复制安装命令+prompt。
- **M4 上传 + 登录**：用户上传 + 标准格式校验 + Forgejo OAuth。
- **M5 附属功能**：评论 + 排行榜。
- **M6 预留接口**：agent 自拉取 prompt/MCP 通道 + client→server 上报 API（stub）+ orchestration manifest 段落地。

---

## 6. 关键风险 / 注意

1. **依赖冲突**（skill 间 + python 包）→ per-skill venv 隔离；skill 间依赖用 manifest `dependencies.skills` 显式解析。
2. **供应链安全**（内网也要）→ checksum 强校验 + 预留发布者签名（gpg / sigstore）；上传校验 + 白名单。
3. **标准格式难改** → M0 把 spec 定扎实 + `manifestVersion` 版本化，升级走迁移。
4. **agent 自拉取安全边界** → 端点限内网 + token；不给任意 URL 拉取。
5. **中立目录 vs agent 目录一致性** → `~/.skillify/skills` 为唯一真相源，agent 目录只是投影；本地 lock 记录来源+版本+已投影 target，install/remove 前检测冲突并提示，避免手改 agent 目录导致漂移。
6. **一 skill 一仓库 vs monorepo** → 建议**一 skill 一仓库**（权限、版本、日志、Release 都更干净），Forgejo 组织下管理。

---

## 7. 待评审 / 后续再定的开放问题

- CLI 用 Python(Typer) 还是 Go？（建议先 Python，后期按分发诉求切 Go）
- agent 自拉取用文档化 REST 端点还是做成 MCP server？
- 上报事件的最小 schema（跑了什么 skill / 成败 / 版本 / 机器标识）与隐私边界。
- 发布者签名何时引入（M2 预留，M6+ 实装）。
