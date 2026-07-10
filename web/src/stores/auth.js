import { defineStore } from 'pinia'

// M-F (docs/review-m2-m6.md): `token` is deliberately excluded from persistence (see
// `persist.paths` below) — an access token sitting in localStorage is readable by any
// script that achieves XSS, with no expiry enforced by the browser. Session restore on
// reload instead goes through keycloak-js's own `check-sso` flow (silent iframe/SSO
// cookie, see lib/keycloak.js's `ensureKeycloakSession` + the router guard that calls it
// before the first route resolves) — the persisted fields here are just UI niceties
// (username display, RBAC-driven menu visibility) that don't grant any access on their own.
// `rbacInfo`/`menus` come from the separate Rbac.Api bridge call (see lib/rbacClient.js).
// `menus` is the raw pruned menu tree the router guard turns into dynamic routes
// (router/dynamicRoutes.js); derived routing state (navTree/authNode/registered routes) lives
// in stores/menu.js. None of it authorizes Skillify's own API calls — those check the
// Keycloak token server-side (M4a).
export const useAuthStore = defineStore('skillify-auth', {
  state: () => ({
    token: null,
    username: null,
    rbacInfo: null, // { id, userid, username, super, project } from Rbac.Api /api/auth/login
    menus: [], // pruned menu tree from Rbac.Api /api/admin/index — source for route generation
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.token),
  },
  actions: {
    setSession(token, username) {
      this.token = token
      this.username = username
    },
    setRbacBridge(rbacInfo, menus) {
      this.rbacInfo = rbacInfo
      this.menus = menus || []
    },
    clear() {
      this.token = null
      this.username = null
      this.rbacInfo = null
      this.menus = []
    },
  },
  persist: { key: 'skillify-auth', paths: ['username', 'rbacInfo', 'menus'] },
})
