# Skillify — 任务拆分（交付 Sonnet 5 开发）

> 依赖顺序：M0 → M1 → M2/M3 可并行 → M4 → M5 → M6。
> 每个任务标注：产出物 / 验收标准。先做 M0、M1 打通闭环，再铺 Web。

> **状态（Sonnet 5 自检，2026-07-09）：M0 + M1 全部完成**，102 个 pytest 测试全绿（`uv run pytest`）。
> **2026-07-09 追加：Opus 4.8 + GPT5.5(Codex) 联合评审通过（`docs/review-m0-m1.md`），并已完成评审要求的加固补丁**：
> - F1 doctor 检查的 agent 集合硬编码错误 → 改为动态遍历 `~/.skillify/agents/*.yaml`（用户裁决：彻底版）。
> - F2 `update` 绕过依赖解析 → 改走 `install_with_dependencies`，新增依赖会在 update 时一并拉取。
> - F3 依赖 skill 是否投影到 agent 目录 → 已裁决维持现状：默认不投影，仅作为根 skill 的内部运行依赖装入中立目录。
> - F4 菱形依赖重复安装 → `install/dependencies.py` 增加本轮 installed 去重 + 版本冲突检测。
> - F5 `requires-python` 与 `tarfile filter="data"` 版本不匹配 → `safe_extract` 改为运行时探测 + 自带等效防护（拒绝符号链接/硬链接/设备文件 + 路径逃逸检查），不再依赖 `filter` 可用性。
> - C1 installer 解包后未复验 manifest 身份 → 增加 staging 目录 + 身份/版本/`validate_skill_dir` 复验，不一致直接失败且不清空已有安装。
> - C2 resolver 选择 Release 资产过宽 → 改为按打包器命名精确匹配 `<namespace>-<name>-<version>.*`，并交叉校验 `.artifact.json` 身份字段。
>
> M2–M6 尚未开始。已知缺口（非决策冲突，已提请并由用户裁决"先不管，继续 M2/M3 开发"）：
> - T0.3 docker-compose 未在真实 Docker 上跑过（本机 Windows 沙箱无 Docker），仅做了 YAML 语法/结构校验，见 `infra/README.md`。
> - T1.5 的 `--index-url`（对应生产环境 devpi）真实网络路径未验证——`uv` 子进程在本沙箱内连不通同机 `127.0.0.1` 的 HTTP 服务（Python `requests` 本身没问题），推测是沙箱防火墙限制 `uv.exe` 子进程出网。已用 `--find-links` 离线路径完整验证了同一套 `uv venv`/`uv pip install` 机制（见 `tests/test_venv_offline.py`、`tests/test_examples.py`），`--index-url` 只是命令行里一行之差；对应集成测试已保留但标记 skip 并写明原因（`tests/test_installer_python_deps.py`）。
> - `skill.yaml` 相对 PLAN.md §3 草案新增了 `namespace`、`tags` 两个字段（实现时发现的必要缺口，非冲突，见 `spec/skill-manifest-v1.md` §3.1，Opus 侧已认可保留）。
> - opencode 的技能目录约定（`~/.opencode/skills/...`）未经验证——本机未装 opencode，是按 claude 目录惯例做的占位默认值，标记在 `skillify/install/agent_defaults.py` 里。

> **2026-07-09 追加二：M2（发布流水线）全部完成**，121 个 pytest 测试全绿。
> - T2.1 选择"webhook→打包服务"而非 Forgejo Actions（PLAN.md §2 给出的是"或"选项之一）：新增
>   `skillify/webhook/`（FastAPI app，HMAC 签名校验 `X-Forgejo-Signature`/`X-Gitea-Signature`）+
>   `skillify-webhook` 控制台脚本；发布逻辑从 `cli/publish_cmd.py` 抽成 `publish/publisher.py`
>   共享给 CLI 和 webhook 两条路径，避免漂移。Tag push（`refs/tags/vX.Y.Z`）触发：拉取该 tag 的
>   源码归档（`ForgejoClient.download_archive`）→ 解包定位 skill 根目录 → 校验 tag 版本与
>   `skill.yaml.version` 一致（C1 同精神）→ 复用 T1.2/T1.3 打包发布链路。非 tag push 返回
>   `ignored` 而非报错。docker-compose 新增 `webhook` 服务 + 根 `Dockerfile`（同样受本机无
>   Docker 限制，未做真实构建验证，见 `infra/README.md`）。
> - T2.2 索引表 `skill_index`（SQLAlchemy，字段 namespace/name/version/description/author/
>   tags/checksum/release_url/published_at）落在与 Forgejo 同一 PostgreSQL 实例的独立数据库
>   `skillify_index`（`infra/postgres-init/`）。写入挂在 `publish_skill_dir` 里，**best-effort**：
>   index DB 未配置/不可达不会让发布失败（Release 本身才是权威来源，索引可从 Forgejo 重建），
>   失败原因通过 `PublishResult.index_error` 冒泡给 CLI/webhook 调用方展示。测试用 SQLite 验证
>   （`tests/test_index.py` + 端到端 `tests/test_publish_index_integration.py`：webhook 发布后
>   直接查询确认可搜到），真实 Postgres 未验证（并入上面的 F6/T0.3 已知缺口）。

> **2026-07-09 追加三：M3（Web 社区站）全部完成**，130 个 pytest 测试全绿；前端框架用户裁决选
> **Vue3**。
> - T3.1 `skillify/web/`（FastAPI，`skillify-web` 控制台脚本，端口 8089）：`/api/skills`
>   （列表，支持 `?q=` 走 T2.2 索引搜索）、`/api/search`、`/api/skills/{namespace}/{name}`
>   （详情：聚合索引数据 + Forgejo 的 README/SKILL.md 原文 `ForgejoClient.get_raw_file` 新增
>   + 按 C2 同规则精确匹配的 tarball/checksum 下载直链）、`/api/skills/{namespace}/{name}/install`
>   （安装命令 + agent prompt；真正的 agent 自拉取端点/MCP 是 T6.1，这里只是文本生成占位）。
>   Forgejo 聚合是 best-effort：未配置/查询失败时详情接口仍返回索引数据，只是 readme/tarballUrl
>   等字段为 null，不 500。
> - T3.2 `web/`（Vite + Vue3，独立 npm 项目，不进 Python 包）：列表页（搜索框防抖调用
>   `/api/search`）+ 详情页（`markdown-it` 渲染 + `shiki` 高亮 README/SKILL.md 两个 tab、
>   安装命令与 agent prompt 一键复制、版本历史、下载链接）。**做了真实的端到端验证**（不只是
>   `npm run build` 编译通过）：起了 `skillify-web`（配 SQLite 索引库）+ `npm run dev`
>   （Vite 代理 `/api` 到后端），用 Playwright 起无头 Chromium 实际加载页面、点进详情页、截图
>   确认渲染正确、控制台无报错（`web/e2e-check.cjs`，可重跑）；另外用 Node 直接调用
>   `renderMarkdown()` 单测确认 Shiki 语法高亮真正产出高亮后的 HTML（非仅静态调用未验证）。
> - 已知缺口：Vite 生产构建产物较大（shiki 按语言分包懒加载，单个语言 chunk 可到几百 KB，见
>   构建输出的 chunk-size 警告）——不影响首屏正确性，是后续可选的打包体积优化（可用 shiki 的
>   fine-grained bundle import 替代 `createHighlighter` 全量语言列表）。生产环境静态资源如何
>   服务（nginx / FastAPI 挂载 `dist/`）尚未定，属于部署收尾，不在 T3.2 验收范围内。

> **2026-07-09 追加四：M4（登录 + 上传）全部完成，含一次登录方案变更**，142 个 pytest 测试全绿。
> **方案变更详情见 PLAN.md §0.1**（用户裁决：Keycloak 前端直连 + 复用现有 .NET `Rbac.Api` 做
> 菜单级权限，取代原 "Forgejo OAuth 登录"）。实现要点：
> - `skillify/web/auth.py`：Keycloak JWT 校验（PyJWT + JWKS，真实 RSA 签名/issuer/audience/
>   过期校验，非 trust-all）。`tests/fake_keycloak.py` 现造 RSA 密钥对 + 起本地 JWKS 端点验证
>   （`tests/test_web_auth.py`：合法/错 audience/过期/篡改/未配置/无 audience 六种场景全测）。
>   只保护写接口（上传）；T3.1 原有匿名浏览/搜索接口不变——用户明确裁决"RBAC 不保护现有浏览
>   接口，走 Keycloak 校验即可"，此处理解为浏览/搜索维持匿名（未要求登录才能看）。
> - `POST /api/skills/upload`：zip 安全解压（`web/upload.py`，防 zip-slip/符号链接）→ 目录改名
>   对齐 manifest `name`（新提取的公共函数 `common/skill_dir.py:rehome_to_declared_name`，
>   webhook handler 也改用它去重）→ T0.2 校验器 → T1.2/T1.3 打包发布链路复用。
> - 前端 `web/src/lib/keycloak.js`（redirect+PKCE 登录/静默会话恢复/token 刷新轮询）+
>   `stores/auth.js`（Pinia + `pinia-plugin-persistedstate`，仿照 `E:\Web\flow\web` 的
>   token 持久化方式）+ `lib/rbacClient.js`（前端直连 `Rbac.Api` 的 `/api/auth/login` +
>   `/api/admin/index`，仿 `E:\Web\flow\web\src\api\backend\rbac\bridge.ts` 的 token-bridge
>   模式）+ `UploadView.vue` + 路由守卫。**做了真实端到端验证**：Playwright 无头浏览器验证
>   ①未配置 Keycloak 时登录按钮不渲染、直接访问 `/upload` 被路由守卫弹回列表页（均无控制台
>   报错）；②模拟已登录状态（预置 Pinia 持久化的 localStorage）后 Upload 导航正确出现、
>   上传表单正确渲染。后端 6 个上传场景（成功发布/未认证 401/非 zip 400/校验失败 422/重复
>   版本 409/路径穿越 400）全部走真实 fake Forgejo + fake Keycloak 集成测试，非纯 mock。
> - **已知缺口（本次新增）**：
>   - Keycloak 和 `Rbac.Api` 的真实 realm/client ID/服务地址不存在于本开发环境，全部代码用
>     环境变量占位（`VITE_KEYCLOAK_REALM_URL` 等），未接入真实实例联调。
>   - 未实现"逐用户 Forgejo OAuth token"：上传发布仍用 Skillify 后端自己的服务账号
>     `forgejo_token`，上传者身份只是写进 Release notes/索引 author 字段做记录，不是真的
>     "以该用户身份操作 Forgejo"。真正的 Keycloak↔Forgejo↔Skillify 三方 SSO token 链路是
>     一块独立且更大的工作量，本轮未被要求实现，留作后续评审判断是否需要。
>   - `Rbac.Api` 当前 checked-out 的 dev 配置本身零签名校验（`TrustedJwt` 模式），且没有任何
>     真实 Keycloak 信任关系配置——这是该 .NET 服务自身的问题，不是 Skillify 这边引入的，但
>     joint review 时应该知会一声，因为"复用现成 RBAC"这个决策的前提是那个服务本身是安全的。

> **2026-07-09 追加五：M5 + M6 全部完成，M0-M6 整套任务清单跑完**，168 个 pytest 测试全绿。
> - T5.1 评论：`skill_comments` 表（Postgres/SQLite 通用 schema），公开读 + Keycloak 登录写
>   （复用 M4a 校验依赖），`CommentSection.vue` 挂在详情页底部。
> - T5.2 排行榜：新增 `skill_events`（安装/运行事件，供 T6.2 复用同一张表）+ `skill_ratings`
>   （每用户每 skill 一条 1-5 分，重复评分更新而非累加）两张表；`GET /api/leaderboard?
>   dimension=installs|rating|recent` 聚合排序。`LeaderboardView.vue` + 详情页 `RatingWidget.vue`。
>   **注意依赖闭环**：安装量指标的数据源是 `skillctl install` 成功后上报的 install 事件——这一
>   步的上报逻辑实际是随 T6.2 一起实现并接回来的（见下）,否则排行榜的"安装量"维度会一直是 0。
> - T6.1 Agent 自拉取通道：`agent_prompt()` 从占位文案改成真正可执行的 fetch+校验+安装配方
>   （GET 详情接口拿 tarballUrl/checksumUrl → 下载 → 校验 sha256 → 解压到 agent 技能目录），
>   写了 `docs/agent-self-pull.md` 记录协议与已知安全缺口（**token 认证未实现，仅文档化**——
>   PLAN §4/§6.4 要求的"限内网+token"目前只有"限内网"落地，token 层是明确留白的后续工作，
>   因为 T6.1 本身被 TASKS.md 定性为"预留接口"里程碑项，不是加固任务）。
> - T6.2 上报 API：`skillify/common/telemetry.py`，默认关闭（需要同时配置 `web_base_url` +
>   `reporting_enabled` 才会真的发请求），复用 T5.2 的 `skill_events` 表和端点。隐私边界在
>   模块 docstring 里写清楚：只收 skill 标识+事件类型+成败+随机生成的机器 id，不收用户名/
>   IP/技能输入输出等任何东西——schema 本身就是强制手段（`SkillEvent` 表没有多余字段）。
>   `skillctl install` 成功后会尝试上报（best-effort，不阻塞，失败静默），机器 id 首次生成后
>   缓存在 `~/.skillify/machine_id`（随机 UUID，非硬件指纹）。
> - T6.3 orchestration 字段：`skill_index` 表新增 `orchestration` JSON 列，从 `pack_skill` 一路
>   带到索引，新增 `GET /api/skills/{namespace}/{name}/orchestration` 只读端点暴露给未来编排器
>   —— 没有实装任何编排引擎，纯粹是"字段没被吞掉、能查到"。
> - 全部前端改动做了真实浏览器验证（Playwright 截图 + console 报错检查），不只是编译通过。

---

## M0 · 规范与地基

- [x] **T0.1 定义 skill.yaml spec**
  产出：`spec/skill-manifest-v1.md` + JSON Schema。
  验收：字段齐全（见 PLAN §3），含 manifestVersion、dependencies(python/system/skills)、orchestration/reporting 预留段。

- [x] **T0.2 标准格式校验器**
  产出：`skillify/validator`（Python 库 + CLI 子命令 `skillctl validate <dir>`）。
  验收：能校验目录结构 + SKILL.md frontmatter + skill.yaml schema，给出可读错误。

- [x] **T0.3 本地基础设施 docker-compose**
  产出：`infra/docker-compose.yml`（Forgejo + PostgreSQL + devpi）。
  验收：一键起；Forgejo 可创建组织/仓库/Release；devpi 可作为 pip index 拉包。

---

## M1 · CLI 闭环（MVP 核心）

- [x] **T1.1 skillctl 骨架（Typer）**
  产出：`skillctl` 命令：`init / doctor / validate / publish / install / list / update / remove / search`。
  验收：命令可用，配置文件读 Forgejo/devpi 地址 + token。

- [x] **T1.1a skillctl init（作者模板脚手架）** ← 建议先于 T1.6
  产出：`skillctl init <namespace>/<name> [--template prompt|python]` → 生成标准骨架：`SKILL.md`、`skill.yaml`、`README.md`、`examples/`、（python 模板加 `requirements.txt`）。
  验收：生成物开箱通过 T0.2 校验器；两种模板（纯 prompt / 带 python）都能一步跑通到 publish。

- [x] **T1.1b skillctl doctor（环境自检）**
  产出：`skillctl doctor` 检查：Forgejo 可达、devpi 可达、token 有效、Python/uv 存在、skills 安装目录可写、Claude/Codex 目标目录存在、必需系统命令齐全。
  验收：逐项输出 ✓/✗ + 修复提示；任一项失败退出码非 0，可用于 CI 预检。

- [x] **T1.2 打包 + checksum**
  产出：打包器：目录 → tarball + sha256 + 生成的构件 manifest。
  验收：产物可复现（同输入同 checksum），元数据完整。

- [x] **T1.3 publish 到 Forgejo**
  产出：`skillctl publish` → push + 创建/上传 Release 构件。
  验收：Forgejo 上出现带构件与 checksum 的 Release。

- [x] **T1.4 install 闭环（中立目录）**
  产出：`skillctl install <name>[@version] [--target claude|opencode|codex|project]` → 下载构件 → 校验 checksum → 解压到**中立目录 `~/.skillify/skills/<namespace>/<name>`（真相源）** → 建 per-skill venv（uv）→ 从 devpi 装依赖 → 写 lock。
  验收：装完后中立目录结构完整（skills/venvs/locks/cache/config）；lock 记录来源+版本+校验；冲突检测生效。**不**直接写 agent 目录。

- [x] **T1.4a Agent 适配层**
  产出：`~/.skillify/agents/<agent>.yaml` 规则（目标目录/链接方式/格式映射）；install 按 `--target` 把中立目录投影到 agent 目录（未指定则投影到 manifest 声明且本机已装的 agent）。首批适配 **claude + opencode**。
  验收：`--target claude` 与 `--target opencode` 均能让 skill 在对应 agent 生效；Linux 用 symlink，Windows(外网测试)降级 copy；`remove` 能同时清理投影。

- [x] **T1.5 依赖解析（skill 间 + python）**
  产出：解析 `dependencies.skills` 递归安装；python 走 devpi。
  验收：带依赖的 skill 一条命令装全。

- [x] **T1.6 示例 skill ×2–3（含 python 依赖）**
  产出：`examples/` 下手写示例。
  验收：走完"publish → install → 本机运行"全链路。

---

## M2 · 发布流水线

- [x] **T2.1 CI/webhook 打包服务**
  产出：Forgejo Actions 或 webhook→打包服务：push/tag → 校验 manifest → 打包 → 生成 checksum → 发布 Release。
  验收：作者只需 push，构件自动产出。

- [x] **T2.2 索引入库**
  产出：Release 事件 → 写 PostgreSQL 索引表（name/version/desc/author/tags/checksum/时间）。
  验收：新发布后 Web/搜索可查。

---

## M3 · Web 社区站（与 M2 可并行）

- [x] **T3.1 FastAPI 后端**
  产出：`/skills` 列表/详情、`/search`、构件下载地址、安装命令+prompt 生成。
  验收：聚合 Forgejo + Postgres，接口可用。

- [x] **T3.2 前端（Vue3 或 React）**
  产出：列表页 + 详情页（Markdown+Shiki 渲染 README/SKILL.md）+ 搜索 + 一键复制安装命令/agent prompt。
  验收：能浏览、搜索、复制安装。

---

## M4 · 上传 + 登录

- [x] **T4.1 登录**（设计变更，见 PLAN.md §0.1：Keycloak 前端直连 + RBAC 菜单桥接，不再是
  "Forgejo OAuth 登录"）
  验收：Vue3 前端 `keycloak-js` 重定向登录 + 会话静默恢复/刷新；已登录用户前端直连外部
  `Rbac.Api` 做 token-bridge 拿菜单树，控制"上传"入口可见性；未登录直接访问 `/upload` 被
  路由守卫弹回列表页。

- [x] **T4.2 用户上传 + 标准校验**
  产出：`POST /api/skills/upload`（`skillify/web/app.py`），Keycloak JWT 校验（`web/auth.py`，
  真实 RSA JWKS 签名验证，非 mock）保护；浏览器上传 skill 目录的 zip → 安全解壳
  （`web/upload.py`，防 zip-slip/符号链接，同 `install/extract.py` 的防护思路）→ 复用 T0.2
  `validate_skill_dir` → 复用 T1.2/T1.3 打包发布链路（`publisher.py`，服务账号 token）。
  Vue3 侧 `UploadView.vue` 表单 + 结果展示。
  验收：不合规包 422 返回结构化 issue 列表并给出原因（`tests/test_web_upload.py`
  `test_upload_invalid_skill_returns_structured_issues` 验证）；重复版本 409；未认证 401；
  zip 路径穿越 400。

---

## M5 · 附属功能

- [x] **T5.1 评论**（Postgres，skill 详情页）
- [x] **T5.2 排行榜**（安装量/评分/时间维度）

---

## M6 · 预留接口

- [x] **T6.1 Agent 自拉取通道**
  产出：文档化内网端点（或 MCP server）+ 每个 skill 页面的可粘贴 prompt。
  验收：Claude Code agent 粘贴 prompt 即可自行 fetch+校验+安装；限内网+token。

- [x] **T6.2 client→server 上报 API（stub）**
  产出：本机运行 skill 后上报（skill/版本/成败/机器标识）；服务端接收入库。
  验收：接口通，schema 最小可用，隐私边界文档化。

- [x] **T6.3 orchestration manifest 段落地**
  产出：skill.yaml `orchestration` 字段解析 + 预留 hook 接口（不实装编排引擎）。
  验收：字段被解析并暴露给未来编排器。
