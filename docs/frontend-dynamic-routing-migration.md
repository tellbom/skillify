# Skillify 前端迁移方案：对齐 flow/web 后端驱动动态路由

> 起草：Opus 4.8（逐文件通读 `E:\Web\flow\web` 与 `E:\skillify\web` 后产出）。日期：2026-07-10。
> 性质：迁移设计方案，交 GPT5.6 + 用户联合评审。落地对象：Sonnet 5 开发。
> 触发：GPT5.6 建议 Skillify 前端对齐公司内网统一的"后端菜单树驱动路由 + RBAC + Keycloak"范式（`flow/web`）。用户裁决：内网架构一致性优先于当前轻量实现，接受额外复杂度。

---

## 实施状态（2026-07-10，已执行激进一次性切换）

> 用户 2026-07-10 追加裁决：**立即执行激进一次性切换**（aggressive one-way cutover），不保留静态业务路由作为过渡、不等真实 RBAC 数据再实现前端。已按此落地，下述为实际完成情况。

**已完成并本地验证：**
- 路由引擎 `web/src/router/dynamicRoutes.js`（移植自 flow `utils/router.ts`，plain-JS 重写）——`buildRouteRecords`/`buildNavTree`/`buildAuthNode`/`generateRoutes`/`removeDynamicRoutes`，flow 词汇（`type`/`menu_type`/`extend`），`extend: add_rules_only` = 隐藏路由。
- 单测 `web/tests/dynamicRoutes.spec.js`（vitest，fixture 仅存在于测试）——**13/13 通过**：路由生成/隐藏路由/按钮不建路由/未解析组件跳过不崩/参数路由 props/`removeDynamicRoutes` 只留框架路由。
- 框架级静态路由 `web/src/router/index.js`（仅 login/401/403/404/layout/catch-all）+ 全局守卫 `web/src/router/guard.js`（首航 bootstrap → `generateRoutes` → 重导航；无回退，RBAC 无数据则显式失败跳 /401）。
- `web/src/stores/menu.js`（navTree/authNode/registeredRouteNames/bootstrapError，不持久化）。
- 布局壳 `web/src/layouts/AppLayout.vue`（导航遍历 `menuStore.navTree`）+ 错误页 `views/error/{NotFound,Forbidden,TokenExpired}.vue` + `views/Login.vue`。
- 引导/清理改造：`keycloak.js` 加 `initialized` 防 `kc.init` 二次调用（改用 `kc.login()` 重定向）；`authBootstrap.bootstrapSession()` 返回是否已认证、`logout(router)` 显式 `removeDynamicRoutes` + `menu.reset()`；`App.vue` 瘦身为 `<router-view/>`；`stores/auth.js` 移除冗余 `canUpload`/`findRuleCode`。
- **删除** `web/src/router.js`（4 条静态业务路由，无并行回退）；`main.js` 改指 `./router/index.js`。
- `npm run build` 干净（无 `INEFFECTIVE_DYNAMIC_IMPORT`、596 模块，shiki 大 chunk 为 M3 既有已知项）。

**阻塞在外部数据（用户将于测试网 RBAC 中心登记后自验）：**
- 真实 `GET /api/admin/index` 返回 §6 菜单行 → 登录/刷新/深链/登出端到端 Playwright（当前环境无真实 Keycloak/Rbac.Api，无法在此验证；fixture 不参与运行时）。
- 登记数据后按 §6 定义在测试网通过，生产复用同一份菜单行定义。

---

## 0. 已锁定决策（用户 2026-07-10 裁决）

| 决策点 | 结论 | 影响 |
| --- | --- | --- |
| **迁移范围** | **对齐 flow/web 的契约 + 移植其路由引擎**，用 Skillify 现有 plain-JS / 无 UI 框架栈重写。**不**引入 Element Plus / i18n / NProgress / `useNavTabs` 标签页系统 / BuildAdmin 布局皮肤 | 保留 Skillify 现有 4 个业务视图与轻量栈；只换"路由从哪来" |
| **路由元数据词汇表** | **用 flow/web 的真实词汇**：`type: menu_dir\|menu\|button` + `menu_type: tab\|link\|iframe` + `extend: ''\|add_menu_only\|add_rules_only` + `keepalive`。**隐藏路由用 `extend: add_rules_only` 表达**，不新增 `hidden`/`activeMenu` 字段 | 与内网既有 `/api/admin/index` 契约 100% 同构；隐藏详情页走 flow 既有语义 |
| **RBAC 菜单数据** | **阻塞在真实 Rbac.Api 数据上**：Skillify 的菜单行必须先在 .NET RBAC 权限中心里建好，作为前置条件。**不做 dev 回退、不做 mock 端点** | 本迁移在当前开发环境**无法端到端验证**，直到外部 .NET 侧补齐菜单数据。见 §13 实施顺序 |

> 由决策 3 + GPT5.6"不保留静态业务路由作为并行回退"共同推导出的硬约束：**一旦移除静态业务路由，在真实菜单数据到位前，应用将没有任何业务页面、也无从验证。** 因此本文档是当前唯一无阻塞的交付物；实施按 §13 分阶段、卡在数据前置条件上。

---

## 1. 目标与非目标

**目标**
1. Skillify 所有业务路由的"是否存在"由后端 `GET /api/admin/index` 返回的菜单树决定，前端不再硬编码。
2. 菜单树同时控制**导航可见性**与**路由存在性**（不再是现状的"RBAC 仅隐藏导航链接"）。
3. 递归遍历后端菜单树 → `import.meta.glob` 解析 `component` 字符串 → `router.addRoute()`；登录后与刷新后重建、登出时清除。
4. 与 flow/web 的初始化时序、刷新处理、越权行为、命名/目录约定尽量对齐。
5. 后端 API 鉴权继续独立生效——动态前端路由是**附加的 UI/路由边界，不是**后端权限校验的替代（见 §11）。

**非目标（决策 1 明确排除）**
- 不引入 Element Plus、i18n、NProgress、`useNavTabs` 多标签页/keepalive 系统、4 套布局皮肤、iframe 菜单类型的完整实现（`menu_type: iframe` 契约保留但可暂不落地渲染）。
- 不移植 flow/web 的 BuildAdmin 遗留 axios（`utils/axios.ts`）、member-center 前台栈、BPMN 工作流模块。
- 不改动 Skillify 后端 FastAPI 的鉴权模型（Keycloak JWT 仍是 API 真实边界）。

---

## 2. 现状对比（迁移的起点）

| 维度 | flow/web（目标范式） | Skillify web（现状） |
| --- | --- | --- |
| 栈 | TypeScript + Element Plus + i18n + Pinia | **plain JS** + 无 UI 框架 + Pinia |
| 路由引擎 | `src/utils/router.ts`（`handleAdminRoute`/`addRouteAll`/`addRouteItem`，约 150 行） | `src/router.js` 4 条静态路由，零 `meta` |
| 路由来源 | `GET /api/admin/index` 菜单树 → `addRoute()` | 硬编码 import |
| 组件解析 | `import.meta.glob('/src/views/backend/**/*.vue')`，键 = `component` 字符串 | 无（直接 import 组件） |
| RBAC 作用 | 控制**路由存在 + 导航** | 仅控制**导航可见**（`canUpload`），路由不受控且 fail-open |
| `routePath`/`menus` | 驱动路由生成 | **已从 `/api/admin/index` 取回但基本未用**（只匹配一个 `skillify:upload`） |
| 登录/刷新 | 布局 `onMounted` 里 `ensureKeycloakSession` → bridge → 生成路由 | 路由 `beforeEach` 首航做 `bootstrapSession`（live check-sso） |
| 登出 | `router.go(0)` 硬刷新（无 `removeRoute`） | 清 Pinia + Keycloak logout 重定向 |
| 401/403/404 | 独立静态错误视图 + catch-all → /404；RBAC client 401 拦截重定向 | **无** 404/登录/错误页 |
| 布局 | `layouts/backend/index.vue` 壳 + 侧栏/顶栏组件 | `App.vue` 内联 header+nav+`<router-view>` |
| 前端测试 | —（未评估） | **无单测**，仅手工 `e2e-check.cjs` 冒烟脚本 |

> 关键有利事实：Skillify 的 `rbacClient.js` **已经**在调 `/api/auth/login` + `/api/admin/index`，且 `authBootstrap.js` 已把 `menus` 存进 Pinia——数据管道半通，本迁移是"接上已取回却丢弃的 `routePath`/`menus`"，而非从零搭鉴权。

---

## 3. 从 flow/web 提取/改写的文件（移植清单）

原则：**移植*模式*，不复制*文件***。下列 flow/web 文件是"参考蓝本"，产出是重写为 Skillify plain-JS 等价物。

| flow/web 蓝本 | 分类 | Skillify 产出（新建） | 改写要点 |
| --- | --- | --- | --- |
| `src/utils/router.ts`（`handleAdminRoute`/`addRouteAll`/`addRouteItem`/`getFirstRoute`） | **核心引擎** | `web/src/router/dynamicRoutes.js` | 去 TS、去 `useNavTabs`；`addRoute(parentName,…)` 挂到 Skillify 布局路由；glob 根改为 `/src/views/**/*.vue` |
| `src/router/static.ts` + `src/router/static/adminBase.ts` | 静态路由聚合 | `web/src/router/index.js`（重写现 `router.js`） | 只保留框架级静态路由（§9）+ 布局根 + catch-all；移除 4 条业务路由 |
| `src/stores/navTabs.ts`（`tabsViewRoutes` + `authNode`） | 菜单/权限状态 | 并入 `web/src/stores/auth.js`（扩展）或新建 `web/src/stores/menu.js` | 只保留"菜单树 + authNode（按钮权限 Map）+ 已注册路由名列表"；**不**要标签页/全屏等 UI 状态 |
| `src/api/backend/rbac/types/index.ts`（`MenuNode`/`BackendIndexResult`） | 契约类型 | `web/src/lib/menuTypes.js`（JSDoc typedef）+ `spec/` 文档 | 词汇表见 §5；plain-JS 用 JSDoc 记录形状 |
| `src/views/common/error/{404,Nopermissionpage,Tokenexpiredpage}.vue` | 错误页 | `web/src/views/error/{NotFound,Forbidden,TokenExpired}.vue` | 去 Element Plus，纯 HTML/CSS 重写 |
| `src/layouts/backend/index.vue`（`init()` 引导逻辑） | 布局引导 | `web/src/layouts/AppLayout.vue`（由现 `App.vue` 拆出） | 把现 `App.vue` 的 header+nav 变成布局壳；`onMounted` 承接引导时序（§8）；导航改为遍历菜单树渲染 |
| `src/api/backend/rbac/client/index.ts`（401 拦截） | RBAC axios | 复用 Skillify 现有 `web/src/lib/rbacClient.js` | 已存在，补 401 → 跳登录（§9） |

**已存在、无需从 flow 移植**：`keycloak.js`、`authBootstrap.js`、`rbacClient.js`（Skillify 版已实现同等 bridge 模式，注释里已标注改编自 `flow/web` 的 `bridge.ts`/`keycloak.ts`）。

---

## 4. Skillify 侧新增 / 修改 / 删除

**新增**
- `web/src/router/index.js`：框架级静态路由表 + 布局根 + catch-all（替代现 `router.js`）。
- `web/src/router/dynamicRoutes.js`：移植引擎（`generateRoutes`/`addRouteItem`/`resolveComponent`/`removeDynamicRoutes`）。
- `web/src/layouts/AppLayout.vue`：布局壳（从 `App.vue` 拆出 header+nav+`<router-view>`），承接引导时序 + 菜单树导航渲染。
- `web/src/views/error/{NotFound,Forbidden,TokenExpired}.vue`：错误页。
- `web/src/stores/menu.js`（或扩展 `auth.js`）：`menus` 树 + `authNode` 权限 Map + `registeredRouteNames` 列表。
- `web/src/lib/menuTypes.js`：`MenuNode`/`BackendIndexResult` JSDoc typedef。
- 测试：`web/tests/dynamicRoutes.spec.js`（vitest，纯函数引擎）+ 扩展 `web/e2e-check.cjs`（Playwright 流程，见 §12）。

**修改**
- `web/src/router.js` → 删除并由 `web/src/router/index.js` 取代（移除 4 条业务路由：`skills`/`skill-detail`/`upload`/`leaderboard`）。
- `web/src/App.vue`：瘦身为 `<router-view>` 挂载点或直接由 `AppLayout.vue` 承担；硬编码的 `<nav>`（Leaderboard/Upload 链接）改为遍历菜单树渲染。
- `web/src/lib/authBootstrap.js`：`bridgeToRbac` 成功后调用 `generateRoutes(menus)`；`logout()` 增加 `removeDynamicRoutes()` + 清 `menu` store。
- `web/src/stores/auth.js`：`canUpload` 从"遍历 menus 找 ruleCode"改为读 `authNode` Map（§11）；`menus` 若迁到 `menu.js` 则相应调整。
- `web/package.json`：devDependencies 加 `vitest` + `@vue/test-utils`（引擎单测）。
- `web/vite.config.js`：无需改（`/api`、`/rbacServer` 代理已就位）。

**删除**
- 现 `web/src/router.js` 的静态业务路由块（决策：不保留为并行回退）。
- `App.vue` 中硬编码的 2 条导航链接与 `v-if="canUpload"` 门（由菜单树驱动取代）。

---

## 5. 路由元数据契约（flow/web 真实词汇，决策 2）

Skillify 消费的 `GET /api/admin/index` 响应形状（与 flow/web 同构）：

```jsonc
// BackendIndexResult
{
  "adminInfo": { "id": "", "userid": "", "username": "", "super": false, "project": "skillify" },
  "menus": [ /* MenuNode[]，后端已按当前用户权限裁剪 */ ],
  "routePath": "skills"      // 登录后默认落地路由（当前 Skillify 取回但未用，本迁移接上）
}
```

```jsonc
// MenuNode（每个节点）
{
  "id": "1", "pid": "0",
  "title": "技能市场",            // 导航显示名
  "name": "skills",              // 唯一路由 name
  "path": "/",                   // 路由 path（可含 :param，见 §7）
  "icon": "",
  "type": "menu",               // menu_dir(目录) | menu(页面) | button(权限点，非路由)
  "menu_type": "tab",           // tab(常规页) | link(外链) | iframe(内嵌)
  "url": "",
  "component": "/src/views/SkillListView.vue",  // = import.meta.glob 键（§组件解析）
  "extend": "",                 // '' | add_menu_only(仅导航不建路由) | add_rules_only(建路由但不在导航显示=隐藏路由)
  "keepalive": false,
  "permissionCode": "",
  "ruleCode": "",               // 按钮/动作权限码，如 skillify:upload
  "children": []
}
```

**引擎裁决规则（移植自 flow `addRouteAll`/`addRouteItem`，Skillify 侧固化）：**

| 节点 | 建路由？ | 进导航？ | 说明 |
| --- | --- | --- | --- |
| `type: menu_dir` | 否 | 是（分组） | 纯目录，聚合子菜单 |
| `type: menu, menu_type: tab, extend: ''` | **是** | **是** | 常规页面（列表/上传/排行榜） |
| `type: menu, menu_type: tab, extend: add_menu_only` | 否 | 是 | 仅占导航位，不建路由 |
| `type: menu, menu_type: tab, extend: add_rules_only` | **是** | **否（隐藏）** | **隐藏路由**（详情页），见 §7 |
| `type: button` | 否 | 否 | 进 `authNode` 权限 Map，供页面内动作门控（§11） |
| `menu_type: iframe` | （契约保留） | 是 | 本期可暂不渲染，不报错跳过 |

**组件字符串 → 组件解析**（移植自 flow）：
```js
const views = import.meta.glob('/src/views/**/*.vue')   // 键为完整路径
const component = views[node.component]                  // 后端 component 必须等于 glob 键
if (!component) { console.error(`unresolved component: ${node.component}`); return }  // 跳过并告警，不崩
```
> 与 flow 一致，后端 `component` 字段直接等于 Vite glob 键（如 `/src/views/SkillListView.vue`）。这带来"后端数据耦合前端文件布局"的代价，flow 已接受此耦合；§6 给出精确字符串。

---

## 6. 每个 Skillify 页面所需的后端菜单数据（.NET RBAC 中心需建的行）

> **这是解除决策 3 阻塞的关键交付**：下列菜单行必须由 .NET `Rbac.Api` 侧针对 `project=skillify` 建好并按用户权限裁剪返回。前端 `component` 字符串必须逐字匹配。

| # | title | name | path | type | menu_type | extend | component | ruleCode | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 技能市场 | `skills` | `/` | menu | tab | `''` | `/src/views/SkillListView.vue` | — | 列表首页；`routePath` 默认落地此 |
| 2 | 技能详情 | `skill-detail` | `/skills/:namespace/:name` | menu | tab | **`add_rules_only`** | `/src/views/SkillDetailView.vue` | — | **隐藏路由**（§7），不进导航；父节点=#1 |
| 3 | 上传技能 | `upload` | `/upload` | menu | tab | `''` | `/src/views/UploadView.vue` | `skillify:upload` | 仅有上传权限的用户可见（后端裁剪即可不返回此节点） |
| 4 | 排行榜 | `leaderboard` | `/leaderboard` | menu | tab | `''` | `/src/views/LeaderboardView.vue` | — | 常规页 |
| 5 | 上传（按钮权限） | `skillify:upload` | — | **button** | — | — | — | `skillify:upload` | 进 `authNode`，供页面内/导航动作门控（可与 #3 二选一或并存，见 §11） |

**裁剪语义**：后端按用户角色裁剪菜单——例如无上传权限者，`/api/admin/index` 直接不返回 #3/#5，则前端既不建 `/upload` 路由、也不显示导航项（决策 5：菜单树同时控路由存在与导航可见）。`super` 用户返回全量。

---

## 7. 动态参数路由处理（`/skills/:namespace/:name`）

- **注册**：作为 #2 菜单节点，`path: '/skills/:namespace/:name'`，`component: /src/views/SkillDetailView.vue`。引擎 `addRouteItem` 里 `router.addRoute(layoutName, { path, name:'skill-detail', component, meta:{...}, props:true })`——保留现有 `props: true`（`SkillDetailView.vue` 用 `route.params.namespace/name`）。
- **隐藏（不进导航）**：用 flow 真实词汇 `extend: add_rules_only`（决策 2）——引擎建路由但导航渲染器跳过该节点。**不引入 `hidden` 字段**。
- **activeMenu 等价行为**（详情页时高亮"技能市场"导航项）：详情节点 `pid` 指向列表节点(#1)，导航渲染器按当前路由的父链高亮；即 flow 无独立 `activeMenu` 字段，用菜单树父子关系表达。若后续需要精确 `activeMenu`，作为 `meta` 扩展再议，不阻塞本期。
- **来源链接**：`SkillListView.vue`/`LeaderboardView.vue` 现用具名路由 + params 跳转（`{ name:'skill-detail', params:{...} }`）——具名路由在动态注册后依然可用，无需改调用点。

---

## 8. 登录 + 刷新初始化时序（对齐 flow 的布局引导模型）

现状 Skillify 在路由 `beforeEach` 首航做引导；迁移后改为 **flow 模型：布局 `onMounted` 引导**（因路由要在鉴权后才存在，`beforeEach` 里做重定向更脆）。

**App 启动 / 刷新（F5）：**
1. `main.js` 装 Pinia + router（仅框架级静态路由）→ 挂载。
2. 首航命中：任意深链因动态路由未注册 → 命中 catch-all / 布局根 → `AppLayout.vue` 挂载。
3. `AppLayout.onMounted`：
   a. `!isKeycloakConfigured()` → （决策 3：无回退）直接进 `/login` 或展示"未配置"提示，不再 fail-open 放行业务（现状 fail-open 行为**移除**）。
   b. `ensureKeycloakSession()`（check-sso，静默恢复）→ 无会话 → `login()`（Keycloak 重定向）。
   c. 有会话 → `auth.setSession(token, username)` + `startTokenRefreshPoll(...)`。
   d. `bridgeToRbac(token)`：`rbacLogin` → `getRbacMenus` → 存 `menus`/`authNode`/`adminInfo`。
   e. `generateRoutes(menus)`（移植引擎）→ `router.addRoute()` 批量注册 + 记录 `registeredRouteNames`。
   f. `nextTick` → 若有原始深链目标则 `router.replace(目标)`，否则 `router.replace(routePath || firstRoute)`。
4. 刷新等同重跑：动态路由**不持久化**，每次整页加载都从后端重建（与 flow 一致；`token` 不落 localStorage，`menus`/`rbacInfo` 可持久化以加速首屏但仍以 live 拉取为准）。

**登录后（Keycloak 回跳）**：走同一 `AppLayout` 引导链（3.b→3.f），无独立分支。

**Token 刷新**：`startTokenRefreshPoll` 每 20s `updateToken(30)` 成功回写 Pinia（M-E 已修，保留）。

---

## 9. 401 / 403 / 404 行为（对齐 flow 静态错误页 + 拦截器）

**框架级静态路由（唯一保留的静态路由，GPT5.6 point 1）：**
```js
routes: [
  { path: '/login',  name: 'login',       component: () => import('../views/Login.vue') },   // Keycloak handshake 落地页（新增，现 Skillify 无）
  { path: '/401',    name: 'unauthorized',component: () => import('../views/error/Forbidden.vue') },
  { path: '/403',    name: 'tokenExpired', component: () => import('../views/error/TokenExpired.vue') },
  { path: '/404',    name: 'notFound',     component: () => import('../views/error/NotFound.vue') },
  { path: '/',       name: 'layout',       component: () => import('../layouts/AppLayout.vue'),
    children: [ /* 动态路由 addRoute 到此 name 下 */ ] },
  { path: '/:pathMatch(.*)*', redirect: '/404' },   // catch-all
]
```
- **404**：未匹配任何（含动态）路由 → catch-all → `/404`。注意时序——动态路由注册前的深链会先落 catch-all，故 §8 的 catch-all/布局根需把"原始目标"暂存后在路由就绪后再 `replace`（flow 用 `loading/:to?` 承接，Skillify 用等价的 query/param 暂存）。
- **401（无权限/未登录）**：RBAC client（`rbacClient.js`）拦截 HTTP 401 → 清 `auth` → `router.push('/login')`（补齐，现状缺）。
- **403（token 过期）**：Keycloak `updateToken` 失败 → `startTokenRefreshPoll` 的 `onRefreshFailed` → 清会话 → `/login` 或 `/403`。
- **无中央 guard 判权重定向**：与 flow 一致，错误页靠 catch-all 与拦截器到达，不在 `beforeEach` 里堆权限判断。

---

## 10. 登出 + 动态路由清理

GPT5.6 point 明确要求"登出时移除动态路由 + 相关状态"。**比 flow 更严谨**（flow 仅靠 `router.go(0)` 硬刷新隐式清除）：

`authBootstrap.logout()`：
1. `stopTokenRefreshPoll()`。
2. `removeDynamicRoutes()`：遍历 `menu.registeredRouteNames`，逐个 `router.removeRoute(name)`；清空该列表。
3. 清 Pinia：`auth.clear()`（token/username/rbacInfo）+ `menu.$reset()`（menus/authNode）。
4. `logoutWithKeycloak()`：Keycloak `/logout` 重定向（整页导航，自然兜底清除任何残留内存路由）。

> 显式 `removeRoute` + `$reset` 保证即使"未配置 Keycloak 故不触发整页重定向"的场景下，动态路由与权限状态也被彻底清干净（不依赖硬刷新）。

---

## 11. 权限映射（RBAC 菜单 → 路由/导航；后端仍是真实边界）

**双层，职责分明：**

| 层 | 数据源 | 作用 | 是否安全边界 |
| --- | --- | --- | --- |
| 路由存在 | `menus`（后端按用户裁剪） | 无对应菜单节点 → 不建路由 → 直接 URL 也 404 | **否**（UI/路由边界） |
| 导航可见 | `menus` | 渲染导航项；`add_rules_only`/`button` 不显示 | 否 |
| 动作门控 | `authNode` Map（`type: button` 节点，键=父路径，值=ruleCode 列表） | 页面内按钮/操作是否渲染（如 `skillify:upload`） | 否 |
| **API 鉴权** | 后端 Keycloak JWT（`skillify/web/auth.py`） | **每个读写端点 `require_keycloak_user`（M-A 已落地）** | **是（唯一真实边界）** |

**关键安全声明（写入代码注释 + 本方案）**：动态路由/`authNode` 是**纯 UI/路由重组，不增加任何真实权限**。后端 Skillify 目前 RBAC 授权很薄（仅 Keycloak JWT 全端点校验 + namespace 归属 + `skillify:upload` 概念，无逐端点角色校验，见 `review-m2-m6.md` §3/§9）。**"路由隐藏 ≠ API 受保护"**——移除某菜单只是让前端看不到入口，后端该端点仍必须靠 `require_keycloak_user`（及后续可能的逐端点授权）自我保护。本迁移不改变、也不得让人误以为改变了后端授权强度。

**`canUpload` 迁移**：现状 `stores/auth.js` 遍历 `menus` 找 `ruleCode==='skillify:upload'` 且 fail-open。迁移后：改读 `authNode`（`button` 节点驱动）；上传入口本身也可直接由菜单树 #3 是否返回决定（决策 5）。fail-open 行为需复审——现状 RBAC 不可达时 `canUpload=true`；迁移后建议保持"RBAC 不可达则不显示上传入口"更一致（fail-closed 于 UI 层），但真实拦截仍在后端。此点提请联合评审确认。

---

## 12. 回归测试与验收标准

**能立即跑（不依赖真实 RBAC 数据）：**
- **引擎纯函数单测**（vitest，`web/tests/dynamicRoutes.spec.js`）：给 `generateRoutes(fixtureMenu)` 喂 §6 的 fixture 菜单树（内存数组，**非 mock HTTP 端点**，不违反决策 3），断言：
  - #1/#3/#4 生成常规路由且进导航；#2（`add_rules_only`）生成路由但**不在**导航列表；#5（button）不生成路由、进 `authNode`。
  - 未解析的 `component` 字符串 → 告警且跳过、不抛。
  - `removeDynamicRoutes()` 后 `router` 只剩框架级静态路由。
  - 参数路由 `/skills/:namespace/:name` 具名跳转 params 正确透传。
- **构建校验**：`npm run build` 干净（无未解析 import、无 dead 静态路由引用）。

**阻塞在真实 Rbac.Api 数据（决策 3，作为上线验收门）：**
- **端到端**（Playwright，扩展 `e2e-check.cjs`）：真实 Keycloak 登录 → 真实 `/api/admin/index` 返回 §6 菜单 → 断言列表/上传/排行榜路由可达、详情深链可达且导航高亮列表、无上传权限用户 `/upload` 直接导航 404、登出后动态路由清除（再访问业务路由 → 重定向登录）。
- **裁剪验收**：分别用"有/无上传权限"两个 Keycloak 用户，验证菜单树差异 → 路由存在性差异。

**验收标准（Definition of Done）：**
1. `web/src/router.js` 中 4 条业务路由已删除，仅框架级静态路由存在。
2. 全部业务路由来自 `/api/admin/index`，无硬编码 import 业务视图于路由表。
3. 隐藏详情路由经 `extend: add_rules_only` 生效（可路由、不在导航）。
4. 登录/刷新/登出/深链四条流程按 §8/§10 行为正确（端到端，数据到位后）。
5. 后端所有端点鉴权不变、仍 `require_keycloak_user`（回归 `uv run pytest` 不受影响）。
6. 引擎单测全绿；`npm run build` 干净。
7. 无并行静态业务路由回退残留（GPT5.6 硬要求）。

---

## 13. 前置阻塞与实施顺序

**硬前置（决策 3）**：Skillify 的 §6 菜单行必须先存在于 .NET `Rbac.Api`（`project=skillify`），否则移除静态路由后应用无业务页面、端到端无从验证。

**建议实施顺序（数据无关部分可先行，但破坏性删除卡在数据前置）：**
1. **[无阻塞] 落地方案 + §6 菜单行规格**，交 .NET RBAC 负责人建数据。
2. **[无阻塞] 数据无关脚手架**：新增框架级静态路由、错误页、`AppLayout.vue`、引擎 `dynamicRoutes.js`、`menu` store、引擎单测（喂 fixture）。此阶段**不删**现有静态业务路由（临时并存，仅为让引擎可单测/可构建）。
3. **[阻塞门] 真实 Rbac.Api 返回 §6 菜单** → 联调登录/刷新/深链/登出端到端。
4. **[阻塞门后] 切换 + 删除**：确认动态路由端到端通过后，**一次性删除**静态业务路由与 `App.vue` 硬编码导航（决策：不保留回退）。此步是"不可并行回退"的落点。
5. 端到端 Playwright + 裁剪验收 → 交 GPT 联合评审。

> 注意：第 2 步的"临时并存"仅是**开发期脚手架**，非交付形态；第 4 步必须删除，最终不留并行静态回退（符合 GPT5.6 硬要求）。若用户希望严格"先有数据再动任何代码"，则第 2 步也一并延后——请在评审时明确。

---

## 14. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| **RBAC 数据外部依赖**（决策 3） | 无数据则应用无业务页面、无法验证 | §6 精确规格交 .NET 侧；实施卡在数据门（§13） |
| `component` 字符串耦合前端文件布局 | 前端挪动视图文件 → 后端菜单 `component` 失配 → 该页 404 | 引擎失配告警；视图路径纳入契约文档、变更需同步后端行 |
| 移除 dev fail-open 后本地开发不便 | 未配 Keycloak/RBAC 时本地跑不出业务页 | 决策 3 已接受；开发者需连真实/预发 RBAC 或用引擎单测替代手工验证 |
| 词汇表阻抗（flow 无 `hidden` 字段） | 隐藏路由语义依赖 `add_rules_only` 约定 | §5/§7 固化引擎裁决规则 + 单测覆盖 `add_rules_only` 分支 |
| 前端无测试基线 + 不留回退 | 一次性删静态路由后回归无网兜 | §12 先建 vitest 引擎单测 + Playwright 流程测，作为删除的前置 |
| 误以为"路由隐藏=API 安全" | 安全误判 | §11 显式声明 + 代码注释；后端授权独立收口（并入 `review-m2-m6.md` 后续项） |

---

## 15. 留给 GPT5.6 联合评审的确认项

1. §13 第 2 步"数据无关脚手架临时并存"是否可接受，还是要求"真实数据到位前不动任何前端代码"？
2. §11 `canUpload` 的 fail-open → 建议改 UI 层 fail-closed，是否认可？
3. §6 的 `component` 采用完整 glob 键路径（耦合文件布局，与 flow 一致）vs 改为短名 + 前端前缀映射（解耦但偏离 flow）——保持哪种？
4. `menu_type: iframe`/`link` 本期"契约保留但不渲染"是否可接受。
5. §6 #3（menu 节点携 `skillify:upload`）与 #5（button 节点）是否需并存，还是仅用 button 节点驱动上传入口。
