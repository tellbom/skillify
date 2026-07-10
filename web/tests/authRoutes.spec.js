import { describe, it, expect } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import { resolveComponent, buildRouteRecords, generateRoutes } from '../src/router/dynamicRoutes.js'
import { LAYOUT_ROUTE_NAME } from '../src/router/constants.js'

// N5.1: confirms the *real* import.meta.glob('/src/views/**/*.vue') in dynamicRoutes.js
// (not a test fixture) actually resolves the ported auth-module view files placed under
// src/views/backend/auth/** (docs/frontend-i18n-auth-task-book.md N5.1). If any of these
// paths were wrong, resolveComponent would return null and buildRouteRecords would skip
// the route (logging a console.error) rather than throwing — this test catches that.
describe('N5.1: real glob resolves the ported auth module views', () => {
  const authComponentPaths = [
    '/src/views/backend/auth/admin/index.vue',
    '/src/views/backend/auth/group/index.vue',
    '/src/views/backend/auth/rule/index.vue',
    '/src/views/backend/auth/apiMap/index.vue',
    '/src/views/backend/auth/projectGrant/index.vue',
  ]

  it.each(authComponentPaths)('resolves %s via the real view glob', (path) => {
    expect(resolveComponent(path)).not.toBeNull()
  })
})

// N5.5 menu rows (docs/frontend-dynamic-routing-migration.md §6a) — the auth module's
// "权限管理" group is menu_dir (#6, no component) with 5 tab children (#7-#11).
function authMenuRows() {
  return [
    {
      id: '6', pid: '0', title: '权限管理', name: 'auth', path: '/auth',
      type: 'menu_dir', menu_type: '', extend: '',
      children: [
        {
          id: '7', pid: '6', title: '管理员', name: 'auth-admin', path: '/auth/admin',
          type: 'menu', menu_type: 'tab', extend: '',
          component: '/src/views/backend/auth/admin/index.vue',
        },
        {
          id: '8', pid: '6', title: '权限组', name: 'auth-group', path: '/auth/group',
          type: 'menu', menu_type: 'tab', extend: '',
          component: '/src/views/backend/auth/group/index.vue',
        },
        {
          id: '9', pid: '6', title: '菜单规则', name: 'auth-rule', path: '/auth/rule',
          type: 'menu', menu_type: 'tab', extend: '',
          component: '/src/views/backend/auth/rule/index.vue',
        },
        {
          id: '10', pid: '6', title: 'API映射', name: 'auth-apimap', path: '/auth/api-map',
          type: 'menu', menu_type: 'tab', extend: '',
          component: '/src/views/backend/auth/apiMap/index.vue',
        },
        {
          id: '11', pid: '6', title: '超管授权', name: 'auth-grant', path: '/auth/project-grant',
          type: 'menu', menu_type: 'tab', extend: '',
          component: '/src/views/backend/auth/projectGrant/index.vue',
        },
      ],
    },
  ]
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: { template: '<div/>' } },
      { path: '/', name: LAYOUT_ROUTE_NAME, component: { template: '<router-view/>' } },
      { path: '/:pathMatch(.*)*', name: 'catchAll', redirect: '/login' },
    ],
  })
}

// N5.3: end-to-end route-existence gating. A super user's menu tree includes the auth
// group; a non-super user's /api/admin/index response simply omits it (the backend
// prunes it, per docs/frontend-dynamic-routing-migration.md §6a's cropping semantics).
// This confirms dynamicRoutes.js correctly turns "absent from the menu tree" into
// "route does not exist" — not just "hidden from nav" — for a non-super session.
describe('N5.3: auth module routes only exist when present in the menu tree (super vs non-super)', () => {
  it('registers all 5 auth routes for a super user whose menu tree includes them', () => {
    const router = makeRouter()
    const { registeredRouteNames } = generateRoutes(router, authMenuRows())
    expect(registeredRouteNames.sort()).toEqual([
      'auth-admin', 'auth-apimap', 'auth-grant', 'auth-group', 'auth-rule',
    ])
    for (const name of registeredRouteNames) {
      expect(router.hasRoute(name)).toBe(true)
    }
  })

  it('registers none of the auth routes for a non-super user whose menu tree omits them', () => {
    const router = makeRouter()
    // Non-super: backend never returns the "权限管理" node at all (server-side pruning).
    const { registeredRouteNames } = generateRoutes(router, [])
    expect(registeredRouteNames).toEqual([])
    expect(router.hasRoute('auth-admin')).toBe(false)
    expect(router.hasRoute('auth-group')).toBe(false)
    expect(router.hasRoute('auth-rule')).toBe(false)
    expect(router.hasRoute('auth-apimap')).toBe(false)
    expect(router.hasRoute('auth-grant')).toBe(false)
  })

  it('the menu_dir group node itself never becomes a route (no component)', () => {
    const records = buildRouteRecords(authMenuRows())
    expect(records.map((r) => r.name)).not.toContain('auth')
  })
})
