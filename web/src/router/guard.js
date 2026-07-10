import { isKeycloakConfigured } from '../lib/keycloak.js'
import { bootstrapSession, login } from '../lib/authBootstrap.js'
import { useAuthStore } from '../stores/auth.js'
import { useMenuStore } from '../stores/menu.js'
import { generateRoutes } from './dynamicRoutes.js'
import { FRAMEWORK_ROUTE_NAMES } from './constants.js'

// Global guard: business routes exist only after the backend menu tree is fetched and
// registered. On the first business-route navigation we:
//   1. restore/establish the Keycloak session (silent check-sso),
//   2. bridge to Rbac.Api and register dynamic routes from /api/admin/index,
//   3. re-resolve the original target now that its route exists.
//
// No fallback of any kind (user decision 2026-07-10): if Keycloak isn't configured, or the
// backend returns no Skillify menu for this user, initialization FAILS VISIBLY (redirect to
// /401 with an on-screen reason) instead of silently opening the app.
export function installAuthGuard(router) {
  let bootstrapped = false

  router.beforeEach(async (to) => {
    // Framework-level static routes (login + error pages) always resolve.
    if (FRAMEWORK_ROUTE_NAMES.has(to.name)) return true

    const menu = useMenuStore()

    if (!isKeycloakConfigured()) {
      menu.setError(
        'Keycloak is not configured on this deployment (VITE_KEYCLOAK_REALM_URL). ' +
          'Skillify cannot load its routes.',
      )
      return { name: 'unauthorized' }
    }

    const auth = useAuthStore()

    if (!bootstrapped) {
      bootstrapped = true
      const authenticated = await bootstrapSession() // sets session + bridges RBAC into auth.menus
      if (authenticated) {
        const generated = generateRoutes(router, auth.menus)
        menu.setGenerated(generated)
        if (menu.hasRoutes) {
          // Dynamic routes now exist — re-resolve the original target.
          return { ...to, replace: true }
        }
        // Authenticated but the backend returned no routable Skillify menu for this user:
        // RBAC rows are missing/not registered. Fail visibly (decision: no fallback).
        menu.setError(
          'No Skillify routes were returned by Rbac.Api for your account. ' +
            'The Skillify menu/permission rows are not registered in the RBAC center yet.',
        )
        return { name: 'unauthorized' }
      }
    }

    if (!auth.isAuthenticated) {
      // Full-page redirect to Keycloak; this SPA navigation never completes.
      await login().catch(() => {})
      return false
    }

    // Authenticated + already bootstrapped, but the target still doesn't match a registered
    // route → genuine 404.
    if (!menu.hasRoutes) {
      return { name: 'notFound' }
    }
    return true
  })
}
