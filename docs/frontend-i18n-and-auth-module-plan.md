# Skillify 前端契约方案：中文化 i18n + 移植 flow/web 授权模块 + Chrome 102/Vite 对齐

> 起草：Opus 4.8（并行子代理逐文件勘察 `E:\Web\flow\web` 与 `E:\skillify\web` 后产出）。日期：2026-07-10。
> 性质：**契约/规格方案**（不含实现）。落地：Sonnet 5。最终交 Opus 4.8 + GPT5.6 联合评审。
> 触发：MVP 评审通过；(1) 整个界面为英文，目标客户以中文为主语言，需全量中文化；(2) 把 `flow/web` 的 `src/views/backend/auth` 授权模块（含依赖组件）移植进 Skillify。

---

## 0. 约束（用户 2026-07-10 明确）

| 约束 | 含义 | 对方案的影响 |
| --- | --- | --- |
| **目标浏览器 Chrome 102** | CSS/JS 不能用超过 Chrome 102 的特性 | **必须把构建产物 JS/CSS 目标降到 ≤ Chrome 102**。当前 Vite 8 默认 `chrome111`——已超标，见 §1 |
| **Vite 端与 flow/web 保持一致** | 否则内网无法测试、内网开发版本产生差异 | Skillify 前端工具链**对齐 flow/web 的 Vite 4.x 栈**，继承其已验证的 Chrome-102 行为，见 §1 |
| **完全不考虑移动端 / 只支持电脑端** | 不做响应式适配 | 不新增 media query；Element Plus 桌面组件即可。**已有响应式代码保留不动** |
| **"已有代码可以不用动"** | 指**移动端适配**层面已有代码无需改 | i18n 中文化**必然要改已有视图**（替换硬编码英文），此项不受"不动"约束——理解为"不为移动端改已有代码" |
| **只写契约，Sonnet 5 改造** | 本文档是规格，不是实现 | 全篇为可交付给 Sonnet 5 的契约 + 验收 |

---

## 1. 头号决策：工具链对齐 flow/web（Chrome 102 的真正根因）

**根因（勘察实证）**：
- Skillify 现在是 **Vite 8**（`node_modules/vite` 默认 `target: "baseline-widely-available"` → `['chrome111','edge111','firefox114','safari16.4']`）。**构建产物 JS 下限是 Chrome 111**，比 Chrome 102（2022-05）晚约 10 个月，esbuild 可自由输出 Chrome 102 不支持的语法且不告警。
- `flow/web` 是 **Vite 4.4.5**（默认 `target: 'modules'` ≈ `es2020`/`chrome87` 基线），天然覆盖 Chrome 102——这正是它能在内网 Chrome 102 跑通的原因。
- 两者都**没有**显式 `build.target`、都没有 `.browserslistrc`；差异**完全来自 Vite 大版本**。

**结论**：把 Skillify 前端工具链**降级对齐 flow/web 的 Vite 4.x 栈**，即可同时满足"Chrome 102 可用"+"与内网基线不产生差异"，且是继承一个**已被内网验证可用**的配置，而非自己猜 target。

### 1.1 版本对齐表（Skillify web 目标态 = flow/web）

| 包 | Skillify 现状 | 目标（对齐 flow/web） | 动作 |
| --- | --- | --- | --- |
| vite | `^8.1.1` | **`^4.4.5`** | 降级（Chrome-102 关键） |
| @vitejs/plugin-vue | `^6.0.7` | **`^4.2.3`** | 降级 |
| vue | `^3.5.39` | **`3.4.38`** | 对齐 |
| vue-router | `^4.6.4` | **`~4.1.6`** | 降级（需回归动态路由引擎，见 §5.4） |
| pinia | `^3.0.4` | **`2.2.2`** | 降级 |
| pinia-plugin-persistedstate | `^4.7.1` | **`4.0.2`** | 降级（注意 `paths`/`pick` 配置差异，见风险） |
| axios | `^1.18.1` | `1.7.4` | 对齐 |
| keycloak-js | `^26.2.4` | `^26.2.4` | 不变 |
| **新增** element-plus | — | **`2.7.8`** | 授权模块所需 UI 框架 |
| **新增** @element-plus/icons-vue | — | **`2.3.1`** | 授权模块图标 |
| **新增** vue-i18n | — | **`9.13.1`** | 中文化基础（§3） |
| **新增** sass | — | **`1.77.4`** | Element Plus 主题 + `--wf-*` token 需要 |
| **新增** @vueuse/core | — | `10.10.0` | 仅 RuleIconSelector 需要（可选） |
| **新增** typescript + vue-tsc | — | `5.4.5` / `2.1.6` | 若采用 TS 移植（见 §2 D2） |
| 保留 markdown-it / shiki | 有 | 保留 | Skillify 既有 README 渲染功能 |
| 保留 vitest | `^2.1.9` | 保留 | 引擎单测，dev 工具不影响运行时/浏览器 |

### 1.2 构建/配置对齐要点（`vite.config.js`）
- **不显式设 `build.target`**——沿用 Vite 4 默认（等同 flow/web），即得 Chrome-102 安全下限。**（不要保留 Vite 8。若因故必须留 Vite 8，则退而求其次显式 `build.target: ['chrome102']` + `build.cssTarget: 'chrome102'` + `esbuild.target` for dev——但这是未经内网验证的近似，不推荐，列为 §10 备选。）**
- 保留 Skillify 现有 `/api`（→ FastAPI 8089）与 `/rbacServer`（→ Rbac.Api）代理；补齐 flow 的 `resolve.alias`（`/@` → `./src/`）以便**逐字移植** flow 授权模块的 `/@/...` import 路径（否则每个 import 都要改写）。
- `main.js` 装载顺序对齐 flow（§3.3）：`pinia` → `await loadLang` → `router` → `ElementPlus` → 挂载。
- CSS 引入顺序对齐 flow：`element-plus/dist/index.css` → `element-plus/theme-chalk/display.css` → 项目 `styles`。

---

## 2. 待批准决策（交 GPT5.6 + 用户联合裁决）

| # | 决策点 | Opus 建议 | 理由 / 代价 |
| --- | --- | --- | --- |
| **D1** | 工具链对齐范围 | **整栈对齐 flow/web（Vite4 + vue3.4 + router4.1 + pinia2.2 + element-plus + vue-i18n + sass）** | 满足用户"vite 与 flow 一致"+ 继承 Chrome-102 验证 + 零内网差异。代价：需在旧栈下回归 M0–M6 前端与动态路由引擎（§5.4） |
| **D2** | 授权模块用 TS 还是转 JS | **引入 TS 支持（`tsconfig` + `allowJs:true`，同 flow）逐字移植；已有 `.js` 不动** | flow 授权模块全是 TS；`allowJs` 让 JS/TS 混存，移植=拷贝而非重写，风险最低。代价：Skillify 首次引入 TS 配置 |
| **D3** | 英文语言包 | **zh-cn 为主 + en 平价**（`fallbackLocale: 'zh-cn'`） | 与 flow 一致；现有字符串本就是英文，做 en 几乎零成本；未来可裁。也可裁为**仅 zh-cn**（更省），列为可选 |
| **D4** | `adminLog` 审计日志视图 | **不移植** | 它用另一套重型 BuildAdmin `baTable` 引擎（`utils/baTable.ts` + `components/table/**` 18+ 文件 + `sortablejs`/`lodash-es`），为一个只读日志页拖入整框架。收益低成本高 |
| **D5** | `EditorDrawer.vue`（@umoteam/editor） | **弃用，group 抽屉改用原生 `el-drawer`** | flow 里 group 只把它当抽屉外壳（`:schema="[]"`），却拖入巨型富文本依赖 `@umoteam/editor` |
| **D6** | `ContactSelector.vue`（admin 人员选择器） | **按现状移植（mock 数据）+ 标注待接真实通讯录** | flow 里它就是 mock（`mockOrgList`/`mockUserList` 硬编码），非阻塞；真实目录集成留后续 |
| **D7** | 授权 5 视图是否补 i18n | **保持 flow 现状：硬编码中文，不补 `$t`** | flow 的 5 个 custom 视图本就硬编码中文、零 `$t`。逐字移植即已是中文，符合"目标中文"。补 i18n 反而偏离逐字拷贝。i18n 工作聚焦**既有英文 Skillify 视图**（§3/§4） |
| **D8** | Skillify 既有 `src/lib/rbacClient.js` 与 flow 的 `api/backend/rbac/client` | **移植 flow 的 rbac client + api 模块；令其 token 源改读 Skillify `useAuthStore`；旧 `rbacClient.js` 合并/废弃** | flow 授权 API 模块都依赖 flow 的 client（`RbacApiError`/分页/401 拦截/`X-Project`）。逐字移植 client 更省，仅需把取 token 从 `useAdminInfo` 适配到 Skillify auth store |

---

## 3. 工作块 B：i18n 基础设施（对齐 flow/web 架构）

> 目标：从零搭建 i18n，**架构与 flow/web 一致**，中文为主。

### 3.1 采用 flow 的 i18n 形态
- 库：`vue-i18n@9.13.1`（v9 线，非 v10+）。`createI18n({ legacy:false, globalInjection:true, locale, fallbackLocale, messages })`。
- 初始化：新建 `src/lang/index.js`（对应 flow `src/lang/index.ts`），`async loadLang(app)` 在 `main.js` 中于 `router`/`ElementPlus` **之前** `await`。
- 语言目录布局（对齐 flow，按目录路径命名空间化）：
  ```
  src/lang/
  ├── index.js              # createI18n + loadLang + editDefaultLang(reload)
  ├── zh-cn/                # 主语言
  │   ├── common.js         # 通用键（Loading/返回/复制…）
  │   ├── skills.js         # 列表/详情
  │   ├── upload.js
  │   ├── leaderboard.js
  │   ├── auth-pages.js     # 登录/错误页
  │   └── comment-rating.js
  └── en/                   # 平价（D3）
      └── (同结构)
  ```
- Element Plus 语言：`App.vue` 用 `<el-config-provider :locale="lang">`，`lang` 取自合并进 i18n 的 `element-plus/es/locale/lang/zh-cn`（同 flow 的 `getLocaleMessage` 方式）。
- 语言存储/切换：新建 `src/stores/locale.js`（Options 风格，同现有 store），`pinia-plugin-persistedstate` 持久化当前语言；切换走 `editDefaultLang(lang) → location.reload()`（同 flow，无热切换）。默认 `zh-cn`。
- 日期本地化：现有视图多处 `new Date(...).toLocaleString()/toLocaleDateString()`——统一按当前 locale（`zh-CN`）格式化（封装一个 `formatDateTime(locale)` 工具，替换裸 `toLocale*`）。

### 3.2 何处接入
- `main.js`：`createApp(App).use(pinia)` → `await loadLang(app)` → `.use(router).use(ElementPlus).mount()`。
- 现有 `main.js` 仅 11 行、`App.vue` 为 `<router-view/>`——接入点干净。

### 3.3 装载顺序（对齐 flow，必须照此序）
`createApp` → `use(pinia)`（loadLang 依赖 config/locale store）→ `await loadLang` → `use(router)` → `use(ElementPlus)` → 自定义指令/图标 → `mount` → 事件总线。

---

## 4. 工作块 C：既有英文界面全量中文化

> 范围 = Skillify **既有英文视图/组件**（授权模块移植进来时已是中文，见 D7）。

### 4.1 需中文化的文件与字符串清单（勘察已逐条提取）

| 文件 | 需替换的可见字符串（要点） | 备注 |
| --- | --- | --- |
| `views/SkillListView.vue` | 搜索占位符、`Loading…`、`Failed to load skills: {error}`、`No skills found.`、`by {author}`、`v{version}` | `{error}` 用命名参数 |
| `views/SkillDetailView.vue` | `← back to all skills`、`Loading…`、`Failed to load skill: {error}`、`by {author} · published {date}`、`{n} installs reported`、CopyButton 两个 label、`download tarball`/`checksum`/`all versions:`、Tab `README`/`SKILL.md`（可留原名）、`No README.`/`No SKILL.md.` | 计数用复数/命名参数；日期本地化 |
| `views/UploadView.vue` | `← back to all skills`、`Upload a skill`、整段说明（含 `<code>`）、`Uploading…`/`Upload`、`Rejected:`、`Published`、`view release`、索引失败提示 | 长段落建议整键 + 占位符 |
| `views/LeaderboardView.vue` | `Leaderboard`、`Most installed`/`Top rated`/`Recently published`（在 `DIMENSIONS` 数组里，需按 key 映射 `t()`）、`Loading…`、`Failed to load leaderboard: {error}`、`Nothing published yet.`、`{n} installs` | 维度标签用 key 而非文案映射 |
| `views/Login.vue` | `internal skills catalog`、`Log in with Keycloak`、未配置提示；`Skillify` 品牌名保留 | tagline 与 AppLayout 共用一键 |
| `views/error/NotFound.vue` | `404`、`This page doesn't exist.`、`Back to Skillify` | |
| `views/error/Forbidden.vue` | `No access`、`You don't have permission…`、`Sign in again` | |
| `views/error/TokenExpired.vue` | `Session expired`、`Your session is no longer valid…`、`Sign in` | |
| `layouts/AppLayout.vue` | `internal skills catalog`、`Log out`；导航项 `{{item.title}}` **来自后端菜单树** | 见 §4.3 |
| `components/CommentSection.vue` | `Comments`、`Loading…`、`Failed to load comments: {error}`、`No comments yet.`、`Add a comment...`、`Posting…`/`Post comment`、`Log in to leave a comment.` | 日期本地化 |
| `components/RatingWidget.vue` | `unrated`、`Rate this skill`(title)、`log in to rate` | |
| `components/CopyButton.vue` | prop 默认 `Copy`、`Copied!` | 默认值改从 i18n 取或调用处传 |

**共用键**：`← back to all skills`（3 处）、`internal skills catalog`（2 处）、`Loading…`（4 处）、各 `Failed to load X: {error}` 归一为 `errors.loadFailed`。

### 4.2 后端来源文本（**不可前端翻译**，明确边界）
`src/lib/api.js` 的 `request()` 抛 `new Error(detail||…)`，`detail` 直接来自后端 JSON（FastAPI 校验器多为英文）；`rbacClient.js` 抛 `resp.data.message`。凡模板里 `{{ error }}`/`{{ postError }}` 显示的都是**服务器原文**——前端 i18n 无法本地化。
- **契约**：这些保持透传；如需中文，要么后端本地化错误消息（单独工作项），要么前端改为"通用中文提示 + 折叠显示原始 detail"。本方案默认**透传**，并在 §10 记为后端协调项。
- 前端自抛的可翻译 `Error`：`authBootstrap.js` 的 Keycloak 未配置文案、`rbacClient.js` 的 fallback 文案——**改为 i18n key**（抛错点或展示层映射），纳入中文化范围。

### 4.3 导航标题 = 后端菜单树（跨系统协调项）
`AppLayout` 导航渲染 `menu.navTree[].title`，来自 Rbac.Api `/api/admin/index`。要中文导航，**菜单行的 `title` 必须是中文**（前端无法翻译后端返回的标题）。
- **契约**：Skillify 的菜单行 `title` 由 RBAC 中心以中文登记（`docs/frontend-dynamic-routing-migration.md` §6 已用中文：技能市场/上传技能/排行榜等）。授权模块菜单行同理用中文（§5.5）。

---

## 5. 工作块 D：移植 flow/web 授权模块

### 5.1 范围裁定
- **移植**：5 个 custom-engine 视图 —— `admin`（管理员）、`group`（权限组/角色）、`rule`（菜单/按钮规则）、`apiMap`（API 权限映射）、`projectGrant`（超管授权）。
- **不移植**：`adminLog`（D4，另一套 baTable 引擎）；`admin/components/GrantDrawer.vue`（孤儿死代码，无引用）。

### 5.2 依赖移植清单（must-copy）

| 类别 | 文件 | 说明 |
| --- | --- | --- |
| 视图 | `views/backend/auth/{admin,group,rule,apiMap,projectGrant}/index.vue` + 各自 `components/*Drawer.vue` | 逐字移植；路径 `/@/...` 靠 §1.2 alias 保留 |
| CRUD 外壳 | `components/claudetable/Commonsearch.vue`、`Commontable.vue` | 5 视图共用；自包含，仅依赖 Element Plus + `--wf-*` token |
| （替换）group 抽屉外壳 | ~~`claudetable/EditorDrawer.vue`~~ → 原生 `el-drawer` | D5，去 `@umoteam/editor` |
| RBAC API | `api/backend/rbac/{index,client,types,admin,group,rule,apiMap,projectGrant,adapters}` | **核心业务逻辑**；client 取 token 改读 Skillify auth store（D8） |
| 人员选择器 | `components/ContactSelector.vue`（admin 用，mock） | D6 |
| 图标选择器（可选） | `components/icon/index.vue` + `svg/*` + `utils/iconfont.ts`（rule 图标字段用） | 保留可编辑图标才需要；否则简化 rule 表单 |
| 状态 | `stores/adminInfo` → **复用 Skillify `useAuthStore`**（有 `rbacInfo.{super,userid}`）或加薄 shim | 4/5 视图读 `.super`/`.userid` |
| 样式 token | `--wf-*`（`workflow-tokens.scss`，**不在 auth 目录内**） | **必须在 flow 全局样式层定位并拷贝**（搜 `--wf-canvas` 定义），否则 Commonsearch/Commontable 渲染破损。见 §5.6 |
| npm | `element-plus@2.7.8`、`@element-plus/icons-vue@2.3.1`、`sass`（、`@vueuse/core` 若图标选择器） | §1.1 已列 |

### 5.3 逐视图所需 Rbac.Api 端点（契约接口，均走 `/rbacServer` 代理到外部 .NET Rbac.Api）
- admin：`GET /api/admin/list`、`POST /api/admin`、`PUT /api/admin/{userid}`、`DELETE /api/admin/{userid}`、`GET /api/group/index?select=true`
- group：`GET /api/group/list`、`POST /api/group`、`PUT /api/group/{groupCode}`、`PUT /api/group/{groupCode}/status`、`PUT /api/group/{groupCode}/rules`、`DELETE /api/group/{groupCode}`、`GET /api/group/index`、`GET /api/rule/tree`、`GET /api/api-map/list`
- rule：`GET /api/rule/list`、`POST /api/rule`、`PUT /api/rule/{ruleCode}`、`PUT /api/rule/{ruleCode}/status`、`PUT /api/rule/{ruleCode}/weigh`、`DELETE /api/rule/{ruleCode}`
- apiMap：`GET /api/api-map/records`、`POST /api/api-map`、`PUT /api/api-map/{id}`、`DELETE /api/api-map/{id}`、`GET /api/rule/tree`
- projectGrant：`GET /api/admin/list`、`PUT /api/project-grant/{userid}/super`

> **Skillify 自己的 FastAPI 后端不涉及**：授权模块纯前端 → 外部 Rbac.Api。后端零改动。这些端点须由 Rbac.Api（.NET）提供；测试网需已具备。

### 5.4 与动态路由引擎的整合（关键）
Skillify 已是后端菜单驱动路由（`router/dynamicRoutes.js`，glob `import.meta.glob('/src/views/**/*.vue')`）。授权 5 视图**作为菜单节点**由 `/api/admin/index` 下发、经现有引擎注册——**不新增静态路由**。
- 视图落位 `src/views/backend/auth/.../index.vue`，则菜单行 `component` = `/src/views/backend/auth/admin/index.vue` 等，匹配 glob。
- **回归**：降级 vue-router `4.6→4.1.6`、pinia `3→2.2` 后，必须重跑 `web/tests/dynamicRoutes.spec.js`（引擎单测）确认 `addRoute(parentName,route)`/`removeRoute`/`hasRoute`/`createWebHistory` 行为一致（这些 API 在 4.1.6 均存在，风险低但须验证）。

### 5.5 授权页菜单行（RBAC 中心需登记，仅超管可见）
| title(中文) | name | path | type | menu_type | extend | component |
| --- | --- | --- | --- | --- | --- | --- |
| 权限管理 | `auth` | `/auth` | menu_dir | — | — | — |
| 管理员 | `auth-admin` | `/auth/admin` | menu | tab | '' | `/src/views/backend/auth/admin/index.vue` |
| 权限组 | `auth-group` | `/auth/group` | menu | tab | '' | `/src/views/backend/auth/group/index.vue` |
| 菜单规则 | `auth-rule` | `/auth/rule` | menu | tab | '' | `/src/views/backend/auth/rule/index.vue` |
| API映射 | `auth-apimap` | `/auth/api-map` | menu | tab | '' | `/src/views/backend/auth/apiMap/index.vue` |
| 超管授权 | `auth-grant` | `/auth/project-grant` | menu | tab | '' | `/src/views/backend/auth/projectGrant/index.vue` |

（词汇表沿用 `docs/frontend-dynamic-routing-migration.md` §5 的 flow 真实词汇。）

### 5.6 `--wf-*` 设计 token（必办前置）
Commonsearch/Commontable 重度依赖 `--wf-canvas/--wf-primary/--wf-radius-*/--wf-space-*/--wf-ink*/--wf-divider/--wf-shadow-card/--wf-font-*` 等 CSS 变量，定义在 flow 全局样式（非 auth 目录）。
- **契约**：Sonnet 5 先在 flow 仓库定位其定义文件（`grep -rn "\-\-wf-canvas" E:\Web\flow\web\src`），整份拷入 Skillify 全局样式并在 `main.js` 引入；否则这两个外壳组件样式破损。

---

## 6. 交付顺序（给 Sonnet 5 的任务分解）

> 依赖序：T1 工具链 → T2 i18n 基础 → (T3 中文化 ∥ T4 授权移植) → T5 路由/菜单整合 → T6 回归验收。

- **T1 · 工具链对齐（Chrome 102 关键，先做）**
  产出：`package.json` 降级到 §1.1 目标态 + 装 element-plus/vue-i18n/sass；`vite.config.js` 加 `/@` alias、装载 Element Plus 全局 + CSS；（D2）加 `tsconfig.json`（`allowJs:true`）。
  验收：`npm run dev`/`npm run build` 通过；构建产物在 **Chrome 102 实机**加载运行无语法错误；既有 4 视图 + 动态路由功能不回归。

- **T2 · i18n 基础设施**
  产出：`src/lang/index.js` + `zh-cn/*` + `en/*`（D3）+ `src/stores/locale.js` + `main.js` 接入 + `App.vue` `el-config-provider`。
  验收：`t()` 可用；默认中文；切换语言 reload 生效；Element Plus 组件为中文。

- **T3 · 既有界面中文化**（依赖 T2）
  产出：§4.1 全部视图/组件字符串替换为 `t(...)`；日期本地化工具；前端自抛 Error 改 i18n key。
  验收：既有 4 视图 + 登录/错误页 + 评论/评分 全中文；后端来源文本按 §4.2 透传（记录已知边界）。

- **T4 · 移植授权模块**（可与 T3 并行）
  产出：§5.2 清单全部落位（TS，逐字移植，D2）；`--wf-*` token 拷入（§5.6）；group 抽屉改原生 `el-drawer`（D5）；rbac client token 源适配 Skillify auth store（D8）；ContactSelector mock 标注（D6）。
  验收：5 视图在 Skillify 内渲染正常；对 Rbac.Api 的 §5.3 端点调用连通（测试网）。

- **T5 · 路由/菜单整合**（依赖 T4）
  产出：授权视图落 `src/views/backend/auth/**`；RBAC 中心登记 §5.5 菜单行（用户侧）；确认经动态路由引擎注册、仅超管可见。
  验收：超管登录后导航出现"权限管理"分组，各子页可达；非超管不下发、路由不存在。

- **T6 · 回归 + 验收**
  产出：重跑 `web/tests/dynamicRoutes.spec.js`（旧栈下）；扩展/新增 i18n 与授权页的 Playwright 冒烟；`npm run build` 干净。
  验收：见 §7。

---

## 7. 验收标准（Definition of Done）

1. **Chrome 102**：构建产物在 Chrome 102 实机运行无 JS/CSS 兼容错误；Vite 栈 = flow/web（Vite 4.x），无显式 target 亦安全。
2. **中文化**：既有全部英文界面（4 视图 + 登录 + 3 错误页 + 评论/评分）默认中文；Element Plus 中文；日期按 `zh-CN`；后端来源文本边界已文档化。
3. **授权模块**：admin/group/rule/apiMap/projectGrant 5 页移植并可用；`adminLog`/孤儿组件未混入；无 `@umoteam/editor` 依赖。
4. **路由整合**：授权页经后端菜单树 + 动态路由引擎注册（非静态路由），仅超管可见；`dynamicRoutes.spec.js` 在降级后仍全绿。
5. **不动移动端 / 桌面端**：无新增响应式代码；既有响应式保留。
6. **后端零改动**：Skillify FastAPI 未改；授权模块仅前端 → 外部 Rbac.Api。
7. `npm run build` 干净（既有 shiki 大 chunk 为 M3 已知项，不计）。

---

## 8. 契约接口点汇总（Sonnet 5 与外部依赖的边界）
- **Rbac.Api（.NET，外部）**：须提供 §5.3 全部端点 + `/api/admin/index` 下发含授权菜单行（§5.5）且按 `super` 裁剪。测试网须先具备（同 `docs/frontend-dynamic-routing-migration.md` 的"阻塞在真实 RBAC 数据"）。
- **RBAC 菜单数据（用户侧登记）**：§4.3 导航标题中文 + §5.5 授权页菜单行中文。
- **flow/web 源**：`--wf-*` token 文件位置（§5.6）、rbac client/api/types（§5.2）、5 视图及组件——均从 `E:\Web\flow\web` 逐字取。
- **Skillify 后端**：无。

---

## 9. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **降级 Vite8→4 / router4.6→4.1 / pinia3→2.2** 破坏既有 M0–M6 前端与动态路由 | 回归风险 | T1 先做并回归；`dynamicRoutes.spec.js` 作为闸门；所用 API 均在旧版本存在 |
| `pinia-plugin-persistedstate` v4.0.2 与现有 `persist:{paths:[]}` 配置差异（v4 用 `pick`/`omit`） | 持久化失效 | T1 校正持久化配置写法 |
| **Element Plus 首次引入** + 既有无 UI 框架视图共存 | 体积/样式冲突 | Element Plus 仅授权模块用；既有视图不改用；`:deep()` 局部覆盖已随视图移植 |
| `--wf-*` token 未找到 | 授权外壳样式破损 | §5.6 定为 T4 前置必办 |
| **后端来源错误文本仍英文** | 中文化不彻底 | §4.2 记为后端协调项；本期透传 |
| Rbac.Api 缺 §5.3 端点 / 测试网无数据 | 授权模块无法端到端验证 | 同既有"阻塞在真实 RBAC 数据"；用户测试网登记后自验 |
| TS 引入（D2）与既有纯 JS 混编 | 构建/类型摩擦 | `allowJs:true`（同 flow）；既有 `.js` 不动，仅授权模块 `.ts` |
| Chrome 102 dev 态 | dev server 未降级也可能用新语法 | 用 Vite 4（dev esbuild 目标同 flow，已内网验证）——这正是"对齐 Vite"而非"只改 build.target"的价值 |

---

## 10. 留给 GPT5.6 联合评审的开放问题
1. **D1 工具链降级范围**：整栈对齐 flow（含 router/pinia 降级 + 回归）是否批准？还是仅降 Vite/plugin-vue、其余保留（则 Chrome-102 需显式 target，且与内网基线仍有 router/pinia 版本差）？与以下得保持一致即可
{
    "name": "build-admin",
    "version": "2.1.3",
    "license": "Apache-2.0",
    "type": "module",
    "scripts": {
        "dev": "node ./src/utils/build-table-renderer.mjs && vite --force",
        "build": "vite build && node ./src/utils/build-table-renderer.mjs",
        "lint": "eslint .",
        "lint-fix": "eslint --fix .",
        "format": "npx prettier --write .",
        "typecheck": "vue-tsc --noEmit"
    },
    "dependencies": {
        "@antv/graphlib": "^2.0.4",
        "@antv/layout": "^1.2.14-beta.8",
        "@antv/x6": "^3.1.6",
        "@element-plus/icons-vue": "2.3.1",
        "@onlyoffice/document-editor-vue": "^1.6.1",
        "@tinymce/tinymce-vue": "^6.3.0",
        "@tiptap/core": "^3.7.2",
        "@tiptap/extension-character-count": "^3.7.2",
        "@tiptap/extension-color": "^3.7.2",
        "@tiptap/extension-font-family": "^3.7.2",
        "@tiptap/extension-highlight": "^3.7.2",
        "@tiptap/extension-image": "^3.7.2",
        "@tiptap/extension-table": "^3.7.2",
        "@tiptap/extension-table-cell": "^3.7.2",
        "@tiptap/extension-table-header": "^3.7.2",
        "@tiptap/extension-table-row": "^3.7.2",
        "@tiptap/extension-text-align": "^3.7.2",
        "@tiptap/extension-text-style": "^3.7.2",
        "@tiptap/extension-underline": "^3.7.2",
        "@tiptap/starter-kit": "^3.7.2",
        "@tiptap/vue-3": "^3.7.2",
        "@umoteam/editor": "^8.1.0",
        "@vueuse/core": "10.10.0",
        "axios": "1.7.4",
        "chart.js": "^4.5.1",
        "chat.js": "^1.0.2",
        "d3": "^7.9.0",
        "d3-org-chart": "^3.1.1",
        "echarts": "^5.6.0",
        "element-plus": "2.7.8",
        "font-awesome": "4.7.0",
        "keycloak-js": "^26.2.4",
        "linqts": "^3.2.0",
        "lodash-es": "4.17.21",
        "mitt": "3.0.1",
        "nprogress": "0.2.0",
        "oidc-client-ts": "^3.3.0",
        "pinia": "2.2.2",
        "pinia-plugin-persistedstate": "4.0.2",
        "print-js": "^1.6.0",
        "prosemirror-state": "^1.4.3",
        "prosemirror-view": "^1.41.3",
        "qrcode.vue": "3.4.1",
        "screenfull": "6.0.2",
        "sortablejs": "1.15.2",
        "tinymce": "^6.8.6",
        "v-code-diff": "1.12.1",
        "vue": "3.4.38",
        "vue-i18n": "9.13.1",
        "vue-router": "~4.1.6",
        "vue3-carousel": "0.3.3",
        "xlsx": "^0.18.5"
    },
    "devDependencies": {
        "@eslint/js": "9.11.1",
        "@types/lodash-es": "4.17.12",
        "@types/node": "20.14.0",
        "@types/nprogress": "0.2.3",
        "@types/sortablejs": "1.15.8",
        "@vitejs/plugin-vue": "^4.2.3",
        "async-validator": "4.2.5",
        "eslint": "9.11.1",
        "eslint-config-prettier": "9.1.0",
        "eslint-plugin-prettier": "5.2.1",
        "eslint-plugin-vue": "9.28.0",
        "esno": "4.7.0",
        "globals": "15.9.0",
        "prettier": "3.3.0",
        "rollup": "3.29.0",
        "sass": "1.77.4",
        "typescript": "5.4.5",
        "typescript-eslint": "8.7.0",
        "vite": "^4.4.5",
        "vue-tsc": "2.1.6"
    }
}

2. **D2 引入 TS**：接受 Skillify 引入 `tsconfig(allowJs)` 以逐字移植授权模块，还是要求转纯 JS（重写、偏离 flow 源）？
Skillify 现有 JavaScript 文件保持不变，不要求把整个项目重构为 TypeScript。flow/web 授权模块原本是 TypeScript 的部分继续保留 .ts 文件、接口类型和数据结构，以降低移植错误并方便后续与 flow/web 对比同步。
3. **D3 语言范围**：zh-cn + en 平价，还是仅 zh-cn？
仅zh-cn
4. **D7 授权 5 视图**保持硬编码中文（不补 i18n）是否可接受（与既有视图 i18n 风格不一致，但与 flow 一致）？
可以接受
5. **§4.2 后端错误文本**：本期透传英文，还是同期推动后端错误消息本地化（额外后端工作项）？
消息本地化
6. **D6 ContactSelector**：admin 页人员选择器暂用 mock 是否可接受上线，还是需先接真实通讯录 API？
接受MOCK数据，进入内网后改造成真实得API,只需要保证与E:\Web\flow\web\src\views\backend\auth保持一致即可，后端API直接替换就可以，本质上是进入当前系统得用户必须被keycloak和RBAC共同授权过
