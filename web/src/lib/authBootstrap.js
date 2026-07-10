import {
  ensureKeycloakSession,
  getKeycloak,
  isKeycloakConfigured,
  loginWithKeycloak,
  logoutWithKeycloak,
  startTokenRefreshPoll,
  stopTokenRefreshPoll,
} from './keycloak.js'
import { getRbacMenus, isRbacConfigured, rbacLogin } from './rbacClient.js'
import { useAuthStore } from '../stores/auth.js'
import { useMenuStore } from '../stores/menu.js'
import { removeDynamicRoutes } from '../router/dynamicRoutes.js'

function currentUsername(kc) {
  return kc.tokenParsed?.preferred_username || kc.tokenParsed?.sub || 'unknown'
}

// Called once from the router guard on the first business-route navigation — silently
// restores a session if the browser already has one (Keycloak SSO cookie), without forcing a
// login redirect, and bridges to Rbac.Api so the menu tree lands in the auth store. Returns
// whether a session is now established (the guard uses this to decide route generation).
export async function bootstrapSession() {
  if (!isKeycloakConfigured()) return false
  const auth = useAuthStore()
  let authenticated = false
  try {
    authenticated = await ensureKeycloakSession()
  } catch (err) {
    console.warn('Keycloak session check failed:', err)
  }
  if (!authenticated) {
    auth.clear()
    return false
  }
  const kc = getKeycloak()
  auth.setSession(kc.token, currentUsername(kc))
  startTokenRefreshPoll((token) => auth.setSession(token, currentUsername(kc)), () => auth.clear())
  await bridgeToRbac(kc.token)
  return true
}

// Called from a "Log in" button click — forces the Keycloak redirect if not already
// authenticated.
export async function login() {
  if (!isKeycloakConfigured()) {
    throw new Error('Keycloak is not configured on this deployment (VITE_KEYCLOAK_REALM_URL)')
  }
  const kc = await loginWithKeycloak()
  if (!kc) return
  const auth = useAuthStore()
  auth.setSession(kc.token, currentUsername(kc))
  startTokenRefreshPoll((token) => auth.setSession(token, currentUsername(kc)), () => auth.clear())
  await bridgeToRbac(kc.token)
}

export async function logout(router) {
  stopTokenRefreshPoll()
  // Remove the dynamically-registered business routes + derived menu state, so a subsequent
  // (re-)login rebuilds them cleanly and nothing survives in the running router. The router
  // is passed in by the caller (AppLayout) to avoid an import cycle
  // (router/index -> guard -> authBootstrap).
  const menu = useMenuStore()
  if (router) removeDynamicRoutes(router, menu.registeredRouteNames)
  menu.reset()
  useAuthStore().clear()
  if (isKeycloakConfigured()) return logoutWithKeycloak()
  return Promise.resolve()
}

// RBAC now controls both frontend route EXISTENCE and menu visibility (backend-driven
// routing, see router/dynamicRoutes.js + docs/frontend-dynamic-routing-migration.md). It is
// still not a security boundary — Skillify's own API calls are authorized server-side by the
// Keycloak JWT (M4a). The menu tree fetched here is what the guard turns into routes.
async function bridgeToRbac(token) {
  const auth = useAuthStore()
  if (!isRbacConfigured()) return
  try {
    const loginResult = await rbacLogin(token)
    const indexResult = await getRbacMenus(token)
    auth.setRbacBridge(loginResult.adminInfo, indexResult.menus)
  } catch (err) {
    console.warn('RBAC bridge failed (menu/permission unavailable):', err.message)
  }
}
