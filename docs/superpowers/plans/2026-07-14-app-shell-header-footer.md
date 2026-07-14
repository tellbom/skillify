# Skillify App Shell Header and Footer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy shared business-page header with the approved prototype-aligned header and add a full themed footer.

**Architecture:** Keep authentication and menu stores in `AppLayout.vue`, and move presentation into focused `AppHeader.vue` and `AppFooter.vue` components. Both components consume plain props; Header emits `logout`, while Footer renders authorized navigation and inert placeholder resources.

**Tech Stack:** Vue 3 SFCs, Vue Router, Pinia, Vitest, `@vue/test-utils`, jsdom, scoped CSS.

## Global Constraints

- Preserve Rbac.Api-driven `menu.navTree`; do not hardcode business routes.
- Preserve the existing `logout(router)` flow and `menu.bootstrapError` rendering.
- Prototype target: 60px sticky translucent header, 1320px content width, 28px horizontal desktop padding, `#80cbc4` accent.
- Placeholder documentation and feedback actions must not navigate and must visibly say `暂未开放`.
- Login and error-page shells remain unchanged.

---

### Task 1: Prototype-aligned application header

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Create: `web/tests/appHeader.spec.js`
- Create: `web/src/layouts/AppHeader.vue`

**Interfaces:**
- Consumes: `navItems: Array`, `username: string`, `isAuthenticated: boolean`, `currentPath: string`.
- Produces: `logout` event and a header with dynamic leaf/group navigation.

- [ ] **Step 1: Add Vue component test dependencies**

Run: `npm install --save-dev @vue/test-utils@2.4.6 jsdom@24.1.3`

Expected: `package.json` and lockfile contain both packages.

- [ ] **Step 2: Write the failing Header tests**

Create tests that mount `AppHeader` with a `RouterLink` stub and assert:

```js
expect(wrapper.get('.brand-accent').text()).toBe('ify')
expect(wrapper.get('.user-avatar').text()).toBe('19')
expect(wrapper.get('[aria-current="page"]').text()).toBe('技能中心')
expect(wrapper.get('.nav-group-menu').text()).toContain('规则管理')
await wrapper.get('.logout-button').trigger('click')
expect(wrapper.emitted('logout')).toHaveLength(1)
```

- [ ] **Step 3: Verify the Header test fails because the component is missing**

Run: `npm test -- appHeader.spec.js`

Expected: FAIL resolving `../src/layouts/AppHeader.vue`.

- [ ] **Step 4: Implement the Header component**

Implement a semantic sticky `<header>` with:

```vue
<AppHeader
  :nav-items="menu.navTree"
  :username="auth.username"
  :is-authenticated="auth.isAuthenticated"
  :current-path="route.path"
  @logout="handleLogout"
/>
```

The component must render `Skill<span class="brand-accent">ify</span>`, derive a two-character uppercase avatar with `?` fallback, render child menus without changing their paths, set `aria-current="page"` for the exact active leaf, and emit `logout` from the button. Style it to the prototype values in Global Constraints with visible hover/focus states.

- [ ] **Step 5: Verify Header tests pass**

Run: `npm test -- appHeader.spec.js`

Expected: all Header tests PASS.

### Task 2: Complete application footer

**Files:**
- Create: `web/tests/appFooter.spec.js`
- Create: `web/src/layouts/AppFooter.vue`

**Interfaces:**
- Consumes: `navItems: Array`.
- Produces: authorized quick links, inert resource actions, internal-use and copyright text.

- [ ] **Step 1: Write the failing Footer tests**

Mount the component with one leaf and one group and assert:

```js
expect(wrapper.findAll('.footer-nav-link')).toHaveLength(2)
expect(wrapper.text()).toContain('使用文档')
expect(wrapper.text()).toContain('问题反馈')
expect(wrapper.findAll('.placeholder-link').every((node) => node.attributes('disabled') !== undefined)).toBe(true)
expect(wrapper.text()).toContain('仅供内部使用')
```

- [ ] **Step 2: Verify the Footer test fails because the component is missing**

Run: `npm test -- appFooter.spec.js`

Expected: FAIL resolving `../src/layouts/AppFooter.vue`.

- [ ] **Step 3: Implement the Footer component**

Flatten visible leaf items recursively into quick links while retaining their backend-provided titles and paths. Render “使用文档” and “问题反馈” as disabled buttons with a `暂未开放` badge. Render `© ${new Date().getFullYear()} Skillify` and `仅供内部使用` in the lower row. Use the same max width, accent, border, and muted color family as the Header.

- [ ] **Step 4: Verify Footer tests pass**

Run: `npm test -- appFooter.spec.js`

Expected: all Footer tests PASS.

### Task 3: Integrate the shared shell and verify the application

**Files:**
- Create: `web/tests/appLayout.spec.js`
- Modify: `web/src/layouts/AppLayout.vue`

**Interfaces:**
- Consumes: `AppHeader`, `AppFooter`, `useRoute()`, existing auth/menu stores and router.
- Produces: full-width sticky Header, flexible Main, bottom Footer for every business route.

- [ ] **Step 1: Write the failing layout contract test**

Read the SFC source and assert the intended component boundary and flex shell:

```js
expect(source).toContain('<AppHeader')
expect(source).toContain('<AppFooter')
expect(source).toContain('<main class="app-main">')
expect(source).toContain('min-height: 100vh')
expect(source).toContain('flex: 1')
```

- [ ] **Step 2: Verify layout test fails against the legacy shell**

Run: `npm test -- appLayout.spec.js`

Expected: FAIL because `AppHeader` and `AppFooter` are absent.

- [ ] **Step 3: Integrate Header and Footer**

Import `useRoute`, `AppHeader`, and `AppFooter`. Replace the inline legacy header with `AppHeader`, keep the error paragraph and router view, pass `menu.navTree` to both components, and place `AppFooter` after main. Change `.app-shell` to a full-width `min-height: 100vh` flex column; move the 1320px width and horizontal padding to `.bootstrap-error` and `.app-main`; set `.app-main { flex: 1; width: 100%; box-sizing: border-box; }`.

- [ ] **Step 4: Run targeted shell tests**

Run: `npm test -- appHeader.spec.js appFooter.spec.js appLayout.spec.js`

Expected: all targeted tests PASS.

- [ ] **Step 5: Run complete verification**

Run: `npm test`

Expected: all Vitest suites PASS.

Run: `npm run type-check`

Expected: exit code 0.

Run: `npm run build`

Expected: exit code 0 and a generated `dist` bundle.

Run: `git diff --check`

Expected: no whitespace errors.

