# 评审结论：前端中文化 i18n + flow/web 授权模块移植 + Chrome102/Vite 对齐（Opus 4.8）

> 评审对象：Skillify 前端 P1–P4（工具链对齐 / i18n 中文化 / 授权模块移植），Sonnet 5 实现。
> 评审依据：`docs/frontend-i18n-and-auth-module-plan.md`（契约）+ `docs/frontend-i18n-auth-task-book.md`（Task 计划书 D1–D8 / N1–N6）。
> 评审方式：Opus 亲自跑 `npm install`/`vitest`/`npm run build`/`vue-tsc` + 2 个并行子评审 agent 逐文件对抗性核验 + Opus 复核关键 seam（PagedQuery 导入、main.js 装载序、rbac client token 源）。日期：2026-07-10。
> 性质：Opus 侧结论，GPT5.6 结论请追加到 §7。

---

## 0. 总体结论：**通过（PASS），可进入测试网端到端验证；有 1 个代码缺陷 + 1 个决策偏差需收口，均非上线阻塞**

实现质量高，忠实于契约与 Task 计划书。四个客观闸门全绿：

| 客观闸门 | 结果 |
| --- | --- |
| 工具链对齐 flow/web（N1.1/N1.2） | ✅ **完全一致**：vite `4.5.14`、vue `3.4.38`、vue-router `4.1.6`、pinia `2.2.2`、element-plus `2.7.8` |
| 动态路由引擎降级后回归（N1.2 硬闸门） | ✅ `dynamicRoutes.spec.js` **13/13**，未回归；总测试 **28 passed**（新增 authRoutes/guard/lang/rbacClient specs） |
| 构建（N6.4 一部分） | ✅ `npm run build` 干净 `✓ built in 6.47s`（仅 shiki 大 chunk 告警，M3 既有项） |
| Chrome 102 安全（§1.2） | ✅ `vite.config.js` **未设 `build.target`**，沿用 Vite4 默认（≈es2020/chrome87），覆盖 Chrome 102；`main.js` 用 `async function bootstrap()` 包裹而非顶层 await，比契约假设更稳 |

**但**当前尚不能标记"全部完成"：(1) 一个真实 TS 导入缺陷（`PagedQuery`），(2) D3 英文语言包被静默降级（en 未做）。另有既有的外部阻塞：真实 Rbac.Api + Keycloak 端到端验证须在测试网做（用户侧）。

---

## 1. 逐决策核对（D1–D8 / 关键节点）

| 项 | 结论 | 证据 |
| --- | --- | --- |
| **D1** 整栈对齐 flow | ✅ VERIFIED | 版本精确匹配（见 §0）；持久化 `persist` 从 `paths`→`pick`（pinia-plugin-persistedstate 4.0.2 正确写法，`stores/auth.js:41`） |
| **N1.2** 降级不破引擎 | ✅ VERIFIED | 引擎单测 13/13；持久化字段仍 `username/rbacInfo/menus`，token 不落盘 |
| **D2** 引入 TS 逐字移植 | ⚠️ PARTIAL | `tsconfig.json`（`allowJs`）已建；rbac api 为 `.ts`；`authBootstrap.js:10` 显式 `.ts` 后缀 import——**Vite 构建 OK**，但 `vue-tsc` 报 **28 error**（见 F1） |
| **D3** zh-cn 主 + en 平价 | ⚠️ DEVIATION | **只建 `src/lang/zh-cn/`，无 `en/`**；`lang/index.js` 只 glob `./zh-cn/*`，只并 element-plus zh-cn locale（见 F2） |
| **D4** 不移植 adminLog | ✅ VERIFIED | `auth/` 下无 adminLog；无 baTable/`components/table` 引入 |
| **D5** 弃 EditorDrawer | ✅ VERIFIED | 全树 `grep umoteam\|EditorDrawer` **零命中**；`GroupFormDrawer.vue:2` 用原生 `el-drawer`；`package.json` 无 `@umoteam/editor` |
| **D6** ContactSelector mock | ✅ VERIFIED（结构微调） | `ContactSelector.vue` 为纯受控组件；mock 数据在消费者 `AdminFormDrawer.vue:307` 且带标注 `// Mock 数据（接口就绪后替换）` |
| **D7** 授权 5 视图硬编码中文 | ✅ VERIFIED | 5 视图 + drawer `grep $t\|useI18n` 零命中；全中文字面量，无残留英文 UI、无断裂 `$t` |
| **D8** 单一 rbac client + token 源 | ✅ VERIFIED（1 处合理偏差） | `client/index.ts` 从 `useAuthStore().token` 取 token（非 flow 的 `useAdminInfo`）；`code===0`/`RbacApiError`/401 拦截齐全；**旧 `lib/rbacClient.js` 已删除**；`authBootstrap` 改用新 client。偏差：baseURL 逻辑比 flow 更正确（flow 的 `getUrl()` 是恒返回 `/rbacServer` 的死代码），文件头已注明 |
| **N4.1** `--wf-*` token | ✅ VERIFIED | `styles/workflow-tokens.scss` 存在且 `main.js:8` 引入；Commonsearch/Commontable 引用的每个 `--wf-*` token 均有定义（逐一交叉核对，无未定义引用） |
| **N4.6** rule 图标选择器 | ✅ VERIFIED（干净简化） | `RuleIconSelector`/`components/icon`/`iconfont` 未移植；`RuleFormDrawer.vue:121` 改纯文本 `el-input` 输入图标类名，`rule/index.vue:38` 用 `<i :class="row.icon">` 渲染——**无悬空 import**，构建通过；简化决策已注释说明 |
| **§5.3** 端点覆盖 | ✅ VERIFIED | admin/group/rule/apiMap/projectGrant 五模块端点齐全（另含 searchAuditLogs 等 bonus） |
| **i18n 既有界面中文化（P3）** | ✅ VERIFIED | 11 个既有 view/组件**零残留英文 UI**；保留项仅 `Skillify`/`README`/`SKILL.md`（§4.1 许可）+ 后端来源 `err.message` 透传（§4.2）；日期改走 `lib/datetime.js`，无裸 `toLocale*` 残留 |

---

## 2. 亮点

- **降级不破引擎**：Vite8→4 / router4.6→4.1 / pinia3→2.2 后，13/13 引擎单测仍全绿，且新增 4 个 spec（authRoutes/guard/lang/rbacClient），测试面扩大到 28。这是本次最大风险点，处理干净。
- **rbac client 收敛**：删除旧 `lib/rbacClient.js`，统一到移植来的 `api/backend/rbac/client`，token 源正确改读 Skillify `useAuthStore`——D8 意图完全落地，无双 client 漂移。
- **诚实的简化 + 注释**：EditorDrawer 剔除、图标选择器降级、ContactSelector mock、baseURL 纠 flow 死代码——每处都有代码注释说明，符合项目"标记而非静默"惯例。
- **中文化彻底**：既有界面无残留英文 UI，插值键（`{error}`/`{n}`/`{author}·{date}`）正确，日期本地化到位。

---

## 3. Findings

### F1 · `PagedQuery` 导入路径错误【MAJOR—代码缺陷，须修，非阻塞构建】
`PagedQuery` **仅**在 `api/backend/rbac/client/index.ts:54` 定义并导出，但 `admin/index.ts:17`、`group/index.ts:18`、`rule/index.ts:10` 都从 `'../types'` 导入它（`types/index.ts` 并未 re-export）。
- **为何构建不报错**：esbuild 擦除 type-only import，不校验来源 → `npm run build` 通过。
- **真实后果**：`vue-tsc --noEmit` 报 **28 error**（Opus 实跑确认）。且有功能性类型后果——`RuleListQuery extends PagedQuery` 丢失 `page` 字段，触发 `rule/index.vue:221` 的 `'page' does not exist in type 'RuleListQuery'`。IDE/CI/未来 typecheck 都会失败。
- **修**：三处改为 `import type { PagedQuery } from '../client'`（或在 `types/index.ts` re-export）。3 行改动。
- **附带**：多数其余 error 是 `useAuthStore`（纯 JS Options store）在严格 TS 下 `rbacInfo` 推断为 `never`，致 5 视图 `.super`/`.userid` 报错。属 D2"JS store × TS 视图"的固有摩擦——建议给 auth store 加 `.d.ts` 或最小类型注解，并决定是否把 `typecheck` 脚本纳入 CI（当前 `vue-tsc` 在 devDeps 但**未接入任何 npm script**，故无门禁）。


### MINOR（择机）
- `errors.rbacLoginRejected`（`lang/zh-cn/errors.js:7`）定义但零引用——死键，清理即可。
- `lang.spec.js` 仅 4 条冒烟断言（locale=zh-cn、单键 `common.loading`、element-plus locale 合入），**非**真正的 key-parity/覆盖测试；且无 en 可比。建议后续补一个"模板 `t()` 键 ↔ lang 文件键"的覆盖校验。
- D6 mock 标注在消费者 `AdminFormDrawer` 而非 `ContactSelector` 组件本身——结构微调，功能等价，可接受。

---

## 4. 无法在本环境验证（既有外部阻塞，非本次实现问题）
- **端到端**：授权 5 视图对 Rbac.Api §5.3 端点的读写、`/api/admin/index` 下发授权菜单行（`frontend-dynamic-routing-migration.md` §6 + 本方案 §5.5）、超管/非超管可见性——须在**测试网真实 Rbac.Api + Keycloak**验证（用户已明确将在测试网登记数据后自验）。
- **Chrome 102 实机**（N1.5/N6.4）：构建产物已确认 target 安全，但"实机加载全部页面无兼容错误"仍需在 Chrome 102 实机跑一次确认。

---

## 5. 放行意见与建议顺序

**通过，可进入测试网端到端验证与 Chrome 102 实机验证。** 收口顺序：
1. **修 F1**：`PagedQuery` 导入源改 `../client`（3 行）；决定是否给 `useAuthStore` 加类型 + 是否把 `vue-tsc` 接入 CI 门禁。——建议先修，因为 D2 引入 TS 的目的就是"可类型校验的忠实移植"，交付不通过 typecheck 的 TS 是质量缺口。
2. **收口 F2**：更新决策记录，明确 D3 = 仅 zh-cn（或补 en/*）。二选一，别留悬空。
3. **测试网端到端**（外部阻塞）：登记授权菜单行 + §5.3 端点连通后，跑登录/刷新/深链/登出 + 5 视图读写 + 可见性裁剪。
4. **Chrome 102 实机**：既有中文界面 + 授权 5 页 + 登录/错误页全量点一遍。
5. MINOR 并入一次清理（死键、lang.spec 覆盖校验、mock 标注位置）。

> F1/F2 均**不阻塞** Chrome 102 浏览器测试与测试网联调，可并行推进；但在标记"P1–P4 全部完成"前应先关掉 F1、明确 F2。

---

## 6. 与既有评审的衔接
- 本次未触及后端；`review-m2-m6.md` 的 M-I 及 MINOR 项状态不变。
- 动态路由引擎（`frontend-dynamic-routing-migration.md`）在降级栈下回归通过，其"阻塞在真实 RBAC 数据"的外部前提对本次授权模块**同样适用**（同一 `/api/admin/index` 通道）。

---

## 7. GPT5.6 侧结论（待追加）
> 留给 GPT5.6；如与本文 findings 有分歧，并列记录交用户裁决。
>
> **待联合裁决的开放项**：F1 是否作为"完成"前置必修 + 是否把 vue-tsc 接入 CI；F2 D3 最终取"仅 zh-cn"还是补 en；`lang.spec` 是否需升级为真正的键覆盖校验。
