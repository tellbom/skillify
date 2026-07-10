# Skillify 前端改造 · Task 计划书（逐节点）

> 起草：Opus 4.8。日期：2026-07-10。执行：Sonnet 5（**逐节点改造，每节点交付后由用户/Opus/GPT 评审再进下一个**）。
> 依据：`docs/frontend-i18n-and-auth-module-plan.md`（契约方案，GPT5.6 已评审）。本书是该契约的**可执行节点分解**。
> 目标：(A) 工具链对齐 flow/web 且 Chrome 102 可用；(B) 既有英文界面全量中文化；(C) 移植 flow/web 授权模块（5 视图）。

---

## 0. 评审基线 · 假定裁决（若 GPT 评审有变更，请指出，仅影响对应节点）

| 决策 | 采用 | 影响节点 |
| --- | --- | --- |
| D1 工具链范围 | **整栈对齐 flow/web**（Vite4 + vue3.4 + router4.1 + pinia2.2 + element-plus + vue-i18n + sass） | P1 全部 |
| D2 授权模块语言 | **引入 TS（`tsconfig` allowJs），逐字移植；已有 .js 不动** | N1.4, P4 |
| D3 语言包 | **zh-cn 主 + en 平价** | P2, P3 |
| D4 adminLog | **不移植** | P4（排除） |
| D5 EditorDrawer | **弃用，group 抽屉改原生 `el-drawer`** | N4.5 |
| D6 ContactSelector | **mock 移植 + 标注待接真实通讯录** | N4.4 |
| D7 授权 5 视图 | **保持硬编码中文，不补 i18n** | P4 |
| D8 rbacClient | **移植 flow client + api，token 源改读 Skillify `useAuthStore`，旧 `rbacClient.js` 合并/废弃** | N4.2 |

**全局规则**：桌面端 only，不新增响应式；既有响应式代码不动；Skillify FastAPI 后端**零改动**（授权模块纯前端 → 外部 Rbac.Api）；每节点独立可回滚（建议每节点一次提交）。

---

## 1. 节点依赖图

```
P1 工具链         N1.1 → N1.2 → N1.3 → N1.4 → N1.5(闸门:Chrome102)
                     │
P2 i18n 基础         └────────────→ N2.1 → N2.2 → N2.3 → N2.4 → N2.5
                                                         │
P3 中文化            ┌────────────────────────────────────┘
(依赖 P2)            N3.1 → {N3.2 ∥ N3.3 ∥ N3.4 ∥ N3.5} → N3.6
P4 授权移植          N4.1(前置:token) → N4.2 → N4.3 → {N4.4 ∥ N4.5 ∥ N4.6 ∥ N4.7 ∥ N4.8}
(依赖 P1;可与P3并行)
P5 路由/菜单整合     N5.1 → N5.2(用户侧) → N5.3
(依赖 P4)
P6 回归验收          N6.1 → N6.2 → N6.3 → N6.4(总闸门)
```

---

## P1 · 工具链对齐（Chrome 102 关键，最先做）

### N1.1 降级核心构建依赖（vite + plugin-vue）
- **前置**：无（起点）。
- **改**：`web/package.json` → `vite ^4.4.5`、`@vitejs/plugin-vue ^4.2.3`；`vite.config.js` 语法按 Vite4 校准（`defineConfig`/`loadEnv` 兼容）。删 `node_modules`+`package-lock.json` 重装。
- **验收**：`npm install` 成功；`npm run dev` 起得来；`npm run build` 成功产出 `dist/`。
- **评审点**：Vite 版本已是 4.x；build 无报错。

### N1.2 降级运行时库 + 回归动态路由引擎
- **前置**：N1.1。
- **改**：`vue 3.4.38`、`vue-router ~4.1.6`、`pinia 2.2.2`、`pinia-plugin-persistedstate 4.0.2`、`axios 1.7.4`。**校正持久化配置**：现有 `persist:{paths:[...]}` 在 persistedstate 4.0.2 的写法（`paths` vs `pick`）——按 4.0.2 实际 API 调整 `stores/auth.js`、`stores/menu.js`。
- **验收**：`npx vitest run` → `web/tests/dynamicRoutes.spec.js` **13/13 全绿**（`addRoute(parentName,route)`/`removeRoute`/`hasRoute`/`createWebHistory` 在 4.1.6 行为一致）；`stores/auth.js` 持久化字段仍生效（token 不落盘、username/rbacInfo/menus 落盘）。
- **评审点**：引擎单测全绿；持久化行为未回归。**这是降级安全的关键闸门。**

### N1.3 引入 Element Plus + sass（全局注册）
- **前置**：N1.2。
- **改**：装 `element-plus 2.7.8`、`@element-plus/icons-vue 2.3.1`、`sass 1.77.4`（、可选 `@vueuse/core 10.10.0`）；`main.js` `app.use(ElementPlus)`；按 flow 顺序引入 CSS：`element-plus/dist/index.css` → `element-plus/theme-chalk/display.css` → 项目样式。
- **验收**：临时放一个 `<el-button>` 能渲染出 Element Plus 样式；`build` 通过；既有 4 视图外观不受影响（Element Plus 全局样式不污染现有 plain 视图——若有污染，记录并局部隔离）。
- **评审点**：Element Plus 可用且未破坏既有视图。

### N1.4 引入 TS 支持 + `/@` 别名（为逐字移植授权模块）
- **前置**：N1.3。
- **改**：加 `web/tsconfig.json`（`allowJs:true`、`paths:{ "/@/*":["src/*"] }`、`types:["element-plus/global"]`，参照 flow）；装 `typescript 5.4.5` + `vue-tsc 2.1.6`；`vite.config.js` 加 `resolve.alias`（`/@` → `./src/`）。**既有 `.js` 不动**。
- **验收**：新建一个 `.ts` 文件能被 Vite 解析；`import x from '/@/lib/api.js'` 能解析；既有纯 JS 构建/单测不回归。
- **评审点**：TS/JS 混编可用；`/@` 别名生效；既有代码零改动。

### N1.5 【闸门】Chrome 102 实机验证
- **前置**：N1.1–N1.4。
- **做**：`npm run build`；把 `dist/` 在 **Chrome 102 实机**（内网/等价环境）加载既有全部页面。确认无 JS 语法错误、无白屏、控制台无兼容性报错。确认**不显式设** `build.target`（沿用 Vite4 默认，等同 flow）。
- **验收**：Chrome 102 上既有界面（列表/详情/上传/排行榜/登录/错误页）全部正常渲染与交互。
- **评审点**：**Chrome 102 可用性达标**——P1 收口，方可进 P3/P4。

---

## P2 · i18n 基础设施（依赖 N1.3）

### N2.1 vue-i18n 安装 + `src/lang/index.js`
- **前置**：N1.3。
- **改**：装 `vue-i18n 9.13.1`；建 `src/lang/index.js`：`createI18n({legacy:false, globalInjection:true, locale, fallbackLocale:'zh-cn', messages})` + `async loadLang(app)`（`import.meta.glob` 聚合 `zh-cn/*`、`en/*`，并合入 `element-plus/es/locale/lang/{zh-cn,en}`）+ `editDefaultLang(lang)`（`location.reload()`）。
- **验收**：`loadLang` 可被 `await`；`t('...')` 在组件内可用（先用占位键验证）。
- **评审点**：i18n 实例可创建、可注入。

### N2.2 语言 store（持久化当前语言）
- **前置**：N2.1。
- **改**：`src/stores/locale.js`（Options 风格，同现有 store），字段 `defaultLang`（默认 `zh-cn`）、`fallbackLang`、`langArray:[{name:'zh-cn'},{name:'en'}]`；`pinia-plugin-persistedstate` 持久化。
- **验收**：切换语言后刷新，选择被记住。
- **评审点**：语言选择持久化正确。

### N2.3 `main.js` 接入 + `App.vue` el-config-provider
- **前置**：N2.1, N2.2。
- **改**：`main.js` 装载序 `createApp → use(pinia) → await loadLang(app) → use(router) → use(ElementPlus) → mount`；`App.vue` 包 `<el-config-provider :locale="lang"><router-view/></el-config-provider>`，`lang` 取 `useI18n().getLocaleMessage(当前locale)`（同 flow）。
- **验收**：应用启动默认中文上下文；Element Plus 内置文案（分页/确认框等）为中文。
- **评审点**：装载顺序正确；Element Plus 语言随之切换。

### N2.4 Element Plus 语言联动校验
- **前置**：N2.3。
- **改**：确认 zh-cn/en 的 Element Plus locale 已合入 i18n messages 且 `el-config-provider` 正确取用。
- **验收**：切 en 后 Element Plus 组件文案变英文，切回中文亦然。
- **评审点**：EP 多语言联动无误。

### N2.5 日期本地化工具
- **前置**：N2.1。
- **改**：建 `src/lib/datetime.js` 封装 `formatDateTime(value, locale)`/`formatDate(...)`，按当前 locale（`zh-CN`/`en`）格式化，用于替换视图里裸 `toLocaleString()/toLocaleDateString()`。
- **验收**：同一时间戳在 zh-cn/en 下格式符合各自习惯。
- **评审点**：日期格式随语言变化。

---

## P3 · 既有英文界面中文化（依赖 P2；范围见契约 §4.1）

### N3.1 语言包文件（zh-cn 主 + en）
- **前置**：N2.1。
- **改**：建 `src/lang/zh-cn/{common,skills,upload,leaderboard,auth-pages,comment-rating}.js` 与 `src/lang/en/` 同构。键覆盖契约 §4.1 全部字符串；共用键（`← back to all skills`、`internal skills catalog`、`Loading…`、`errors.loadFailed({error})`）归一。计数用命名/复数参数。
- **验收**：所有键 zh-cn/en 齐备；无缺键（可写一个简单校验：两 locale 键集合一致）。
- **评审点**：键集完整、双语对齐、命名规范。

### N3.2 SkillListView + SkillDetailView 中文化
- **前置**：N3.1, N2.5。
- **改**：两视图硬编码英文→`t(...)`；日期用 `formatDateTime`；计数用命名参数；Tab `README`/`SKILL.md` 保留原名。
- **验收**：两页默认中文；`{error}`/`{author}`/`{date}`/`{n}` 插值正确；后端来源 `err.message` 按契约 §4.2 透传。
- **评审点**：无残留英文（后端文本除外）；插值正确。

### N3.3 UploadView + LeaderboardView 中文化
- **前置**：N3.1, N2.5。
- **改**：同上；Upload 长段落用整键 + `<code>` 占位；Leaderboard 维度 `DIMENSIONS` 用 key 映射 `t()` 而非文案。
- **验收**：两页默认中文；维度标签随语言切换；日期本地化。
- **评审点**：长段落与维度映射处理正确。

### N3.4 Login + 3 错误页 + AppLayout 中文化
- **前置**：N3.1。
- **改**：Login/NotFound/Forbidden/TokenExpired/AppLayout 文案→`t(...)`；`Skillify` 品牌名与 `{{item.title}}`（后端菜单标题）**不**在此处翻译（见契约 §4.3，属后端数据）。
- **验收**：这些页默认中文；导航标题来自后端（中文由 RBAC 菜单行提供，N5.2）。
- **评审点**：区分了"前端可译"与"后端菜单标题"。

### N3.5 CommentSection + RatingWidget + CopyButton 中文化
- **前置**：N3.1, N2.5。
- **改**：三组件文案→`t(...)`；`CopyButton` 默认 label 从 i18n 取或由调用处传；日期本地化。
- **验收**：评论/评分/复制交互全中文；`Copied!`/`Posting…` 等状态双语。
- **评审点**：组件级文案与状态切换正确。

### N3.6 前端自抛 Error → i18n key
- **前置**：N3.1。
- **改**：`authBootstrap.js`（Keycloak 未配置文案）、`rbacClient.js`（fallback 文案）等**前端自抛**字符串改为 i18n key 或展示层映射。**后端来源 `detail`/`resp.data.message` 仍透传**（契约 §4.2）。
- **验收**：前端自造错误可中文；后端错误按边界透传（文档标注）。
- **评审点**：翻译边界与契约 §4.2 一致。

---

## P4 · 移植授权模块（依赖 P1；可与 P3 并行；范围=5 custom 视图）

### N4.1 【前置必办】定位并拷贝 `--wf-*` 设计 token
- **前置**：N1.3。
- **做**：在 flow 仓库定位 token 定义（`grep -rn "\-\-wf-canvas" E:\Web\flow\web\src`），整份拷入 Skillify 全局样式并在 `main.js` 引入。
- **验收**：Skillify 全局能解析 `--wf-canvas/--wf-primary/--wf-radius-*/--wf-space-*/--wf-ink*/--wf-divider/--wf-shadow-card/--wf-font-*` 等变量。
- **评审点**：token 齐备（否则 Commonsearch/Commontable 破损）。

### N4.2 移植 RBAC API 层（client + types + 各端点 + adapters），适配 token 源
- **前置**：N1.4, N4.1。
- **改**：逐字移植 `api/backend/rbac/{index,client,types,admin,group,rule,apiMap,projectGrant,adapters}`（TS）到 Skillify；**改造 client 取 token 从 flow 的 `useAdminInfo` → Skillify `useAuthStore().token`**；保留 `X-Project`/envelope 解包/`RbacApiError`/401 拦截。**旧 `src/lib/rbacClient.js` 的 `rbacLogin`/`getRbacMenus` 迁移到新 client 并统一**（避免两套 client），`authBootstrap.js` 改用新 client。
- **验收**：`authBootstrap` 走新 client 仍能 `rbacLogin`+`getRbacMenus`（动态路由不回归）；新 API 函数类型完整、可被视图 import。
- **评审点**：单一 rbac client；token 源正确；动态路由/登录未回归。**（这是 P4 的地基节点。）**

### N4.3 移植 Commonsearch + Commontable
- **前置**：N4.1, N1.3。
- **改**：逐字移植 `components/claudetable/Commonsearch.vue`、`Commontable.vue`（自包含，仅依赖 Element Plus + `--wf-*`）。
- **验收**：用一段假数据能渲染搜索栏 + 表格（分页/列显隐/插槽）正常。
- **评审点**：两外壳组件独立可用、样式正常。

### N4.4 移植 admin 视图（+ AdminFormDrawer + ContactSelector mock）
- **前置**：N4.2, N4.3。
- **改**：移植 `auth/admin/index.vue` + `components/AdminFormDrawer.vue` + `components/ContactSelector.vue`（**保留 mock 数据，代码顶部标注"待接真实通讯录 API"**）；读 `useAuthStore().rbacInfo.{super,userid}`（或加薄 shim）。**不**移植 `GrantDrawer.vue`（孤儿）。
- **验收**：管理员列表/增删改抽屉渲染；调用 §5.3 admin 端点（测试网连通则可增删改）。
- **评审点**：admin 页功能完整；mock 已标注；无孤儿组件混入。

### N4.5 移植 group 视图（抽屉改原生 el-drawer）
- **前置**：N4.2, N4.3。
- **改**：移植 `auth/group/index.vue` + `GroupFormDrawer.vue` + `GroupRulesDrawer.vue`；**把 `GroupFormDrawer` 对 `EditorDrawer` 的依赖替换为原生 `el-drawer` 外壳**（去 `@umoteam/editor`，D5）；用 `el-table` 树渲染。
- **验收**：权限组树 + 授权规则抽屉可用；**依赖树无 `@umoteam/editor`**；调用 §5.3 group 端点。
- **评审点**：EditorDrawer 已剔除；group 功能等价。

### N4.6 移植 rule 视图（+ RuleFormDrawer + 图标选择器）
- **前置**：N4.2, N4.3。
- **改**：移植 `auth/rule/index.vue` + `RuleFormDrawer.vue` + `RuleIconSelector.vue` + 依赖 `components/icon/*` + `utils/iconfont.ts`（保留可编辑图标；如裁掉图标字段则可省这几项，需在评审确认）。
- **验收**：菜单/按钮规则树增删改 + 图标选择可用；调用 §5.3 rule 端点。
- **评审点**：图标选择器依赖链完整或已按裁剪方案简化。

### N4.7 移植 apiMap 视图（+ ApiMapCreateDrawer）
- **前置**：N4.2, N4.3。
- **改**：移植 `auth/apiMap/index.vue` + `components/ApiMapCreateDrawer.vue`（规则树选择弹层）。
- **验收**：API 权限映射增删改可用；调用 §5.3 apiMap 端点。
- **评审点**：apiMap 功能完整。

### N4.8 移植 projectGrant 视图
- **前置**：N4.2, N4.3。
- **改**：移植 `auth/projectGrant/index.vue`（超管授予/撤销）。
- **验收**：超管授权切换可用；调用 §5.3 projectGrant 端点。
- **评审点**：projectGrant 功能完整。

---

## P5 · 路由 / 菜单整合（依赖 P4）

### N5.1 授权视图落位 + glob 对齐
- **前置**：N4.4–N4.8。
- **改**：授权视图置于 `src/views/backend/auth/**`，使其 `component` 字符串（如 `/src/views/backend/auth/admin/index.vue`）匹配现有引擎 `import.meta.glob('/src/views/**/*.vue')`。
- **验收**：`buildRouteRecords` 能解析这些 component（用 fixture 加一条 admin 菜单节点验证引擎可注册它）。
- **评审点**：路径与 glob 匹配；引擎可注册。

### N5.2 【用户侧】RBAC 中心登记授权菜单行
- **前置**：N5.1。
- **做（用户/RBAC 管理员）**：在 .NET RBAC 中心为 `project=skillify` 登记契约 §5.5 的菜单行（"权限管理"分组 + 5 子页，**中文 title**，仅 super 可见）。
- **验收**：`GET /api/admin/index` 对超管返回这些节点。
- **评审点**：菜单数据到位（此节点是外部依赖，同"阻塞在真实 RBAC 数据"）。

### N5.3 端到端整合验证（超管可见 / 非超管不可见）
- **前置**：N5.2。
- **做**：超管登录 → 导航出现"权限管理" → 各子页经动态路由引擎注册、可达；非超管登录 → 不下发、路由不存在（直达 URL → 404/401）。
- **验收**：可见性与路由存在性均由后端菜单树控制（符合 `frontend-dynamic-routing-migration.md` 决策）。
- **评审点**：授权模块以动态路由方式生效，无静态路由。

---

## P6 · 回归 + 验收（总收口）

### N6.1 降级栈下引擎单测回归
- **前置**：P1–P4 完成。
- **验收**：`npx vitest run` → `dynamicRoutes.spec.js` 13/13 全绿（旧栈下）。

### N6.2 i18n 冒烟（Playwright）
- **验收**：默认中文；切 en→reload→英文；Element Plus 文案随之切换；日期本地化。既有页无残留英文（后端文本除外）。

### N6.3 授权模块冒烟（对测试网 Rbac.Api）
- **前置**：N5.2 数据到位。
- **验收**：5 视图对 §5.3 端点的读/写连通；super/非 super 可见性正确。

### N6.4 【总闸门】构建 + Chrome 102 验收
- **验收**：`npm run build` 干净（shiki 大 chunk 为 M3 既有项）；`dist/` 在 **Chrome 102 实机**跑通：既有中文界面 + 授权 5 页 + 登录/错误页，全部渲染与交互正常，控制台无兼容错误。
- **评审点**：**全部达标 → 交 Opus + GPT5.6 联合评审。**

---

## 7. 交付与评审节奏
- Sonnet 每完成 1 个节点：提交（建议一节点一 commit）+ 附"验收自检结果"，等评审通过再进下一节点。
- **硬闸门节点**：N1.2（降级不破引擎）、N1.5（Chrome 102）、N4.2（单一 rbac client）、N6.4（总验收）——这四处务必停下评审。
- **外部阻塞**：N5.2（RBAC 菜单数据）、N6.3（测试网 Rbac.Api 端点）——非 Sonnet 可解，需用户/RBAC 侧配合，未就绪不阻塞前序编码。

## 8. 未决/需评审确认（承接契约 §10）
1. D1 整栈降级是否已被 GPT 最终确认（尤其 router/pinia 降级 + 回归成本）。
2. N4.6 是否保留可编辑图标（决定是否移植 icon/iconfont 依赖链）。
3. §4.2 后端错误文本本期"透传英文" vs 同期推动后端本地化。
4. D6 ContactSelector mock 是否可接受先上线。
