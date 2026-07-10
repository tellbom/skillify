import { defineStore } from 'pinia'

// Derived routing state produced from the backend menu tree (see router/dynamicRoutes.js).
// Deliberately NOT persisted: dynamic routes only live in the running router instance and
// are rebuilt from /api/admin/index on every full page load (flow/web does the same). The
// raw menu tree is held in the auth store; this store holds what the UI actually renders.
export const useMenuStore = defineStore('skillify-menu', {
  state: () => ({
    navTree: [], // hierarchical, visible menu items only
    authNode: [], // granted rule codes, e.g. ['skillify:upload'] — UI gating only, not security
    registeredRouteNames: [], // names added via router.addRoute, for logout cleanup
    bootstrapError: null, // set when routing can't initialize (fails visibly, no fallback)
  }),
  getters: {
    hasRoutes: (state) => state.registeredRouteNames.length > 0,
    // in-page action gating (button permissions); never a substitute for backend authz.
    can: (state) => (ruleCode) => state.authNode.includes(ruleCode),
  },
  actions: {
    setGenerated({ registeredRouteNames, navTree, authNode }) {
      this.registeredRouteNames = registeredRouteNames
      this.navTree = navTree
      this.authNode = authNode
      this.bootstrapError = null
    },
    setError(message) {
      this.bootstrapError = message
    },
    reset() {
      this.navTree = []
      this.authNode = []
      this.registeredRouteNames = []
      this.bootstrapError = null
    },
  },
})
