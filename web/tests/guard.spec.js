import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

const state = vi.hoisted(() => {
  const menu = {
    hasRoutes: false,
    setGenerated(result) {
      this.hasRoutes = result.registeredRouteNames.length > 0
    },
    setError: vi.fn(),
  }
  return {
    auth: { isAuthenticated: true, menus: [{ name: 'skills' }] },
    menu,
  }
})

vi.mock('../src/lib/keycloak.js', () => ({
  isKeycloakConfigured: () => true,
}))

vi.mock('../src/lib/authBootstrap.js', () => ({
  bootstrapSession: vi.fn(async () => true),
  login: vi.fn(),
}))

vi.mock('../src/stores/auth.js', () => ({
  useAuthStore: () => state.auth,
}))

vi.mock('../src/stores/menu.js', () => ({
  useMenuStore: () => state.menu,
}))

vi.mock('../src/router/dynamicRoutes.js', () => ({
  generateRoutes(router) {
    router.addRoute('layout', {
      path: '',
      name: 'skills',
      component: { template: '<div>skills</div>' },
    })
    return { registeredRouteNames: ['skills'], navTree: [], authNode: [] }
  },
}))

import { installAuthGuard } from '../src/router/guard.js'

describe('installAuthGuard', () => {
  beforeEach(() => {
    state.menu.hasRoutes = false
    state.menu.setError.mockClear()
  })

  it('re-resolves the root path to the dynamic index route after bootstrap', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/',
          name: 'layout',
          component: { template: '<router-view />' },
        },
        {
          path: '/:pathMatch(.*)*',
          name: 'catchAll',
          redirect: '/404',
        },
      ],
    })
    installAuthGuard(router)

    await router.push('/')
    await router.isReady()

    expect(router.currentRoute.value.name).toBe('skills')
  })
})
