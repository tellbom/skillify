// Backend-driven dynamic route engine.
//
// Ported from E:\Web\flow\web\src\utils\router.ts (handleAdminRoute / addRouteAll /
// addRouteItem), rewritten for Skillify's plain-JS / no-UI-framework stack. See
// docs/frontend-dynamic-routing-migration.md §3/§5.
//
// Responsibilities:
//   - walk the backend menu tree (MenuNode[] from /api/admin/index)
//   - resolve backend `component` strings against import.meta.glob
//   - produce vue-router route records, a nav tree, and an authNode permission set
//   - register/unregister those routes on a router instance under the layout route
//
// This module is PURE except registerDynamicRoutes/removeDynamicRoutes (which mutate the
// router). The build* functions take the glob map as an injectable arg so unit tests can
// pass fixtures — fixtures never participate in the real runtime (user decision 2026-07-10).

import { LAYOUT_ROUTE_NAME } from './constants.js'

// The real view map. Keys are absolute paths like "/src/views/SkillListView.vue"; the
// backend's MenuNode.component must equal one of these keys.
const viewModules = import.meta.glob('/src/views/**/*.vue')

/**
 * @param {string} componentPath
 * @param {Record<string, () => Promise<any>>} [glob]
 * @returns {(() => Promise<any>) | null}
 */
export function resolveComponent(componentPath, glob = viewModules) {
  return glob[componentPath] || null
}

// A node becomes a ROUTE when: it is a tab-type page with a component, and it isn't a
// nav-only placeholder. Mirrors flow's addRouteAll skip of `extend == 'add_menu_only'`.
function shouldCreateRoute(node) {
  if (node.type === 'button') return false
  if (node.extend === 'add_menu_only') return false
  if (node.menu_type === 'iframe' || node.menu_type === 'link') return false // contract reserved, not rendered this phase
  return node.menu_type === 'tab' && Boolean(node.component)
}

// A node appears in NAVIGATION when it is a menu/dir and isn't a hidden (add_rules_only) or
// button node. `add_rules_only` is flow's way to say "register the route but keep it out of
// the menu" — our hidden-route mechanism (e.g. the skill detail page).
function isNavVisible(node) {
  if (node.type === 'button') return false
  if (node.extend === 'add_rules_only') return false
  return node.type === 'menu_dir' || node.type === 'menu'
}

/**
 * Flatten the menu tree into vue-router route records (all nested under the layout route).
 * Child paths are made relative (leading slash stripped) exactly as flow/web does, so they
 * resolve against the layout's "/" — e.g. "/" -> "" (index), "/upload" -> "upload",
 * "/skills/:namespace/:name" -> "skills/:namespace/:name".
 *
 * @param {MenuNode[]} nodes
 * @param {Record<string, () => Promise<any>>} [glob]
 * @param {Array} [out]
 * @returns {Array} vue-router RouteRecordRaw-ish records
 */
export function buildRouteRecords(nodes, glob = viewModules, out = []) {
  for (const node of nodes || []) {
    if (shouldCreateRoute(node)) {
      const component = resolveComponent(node.component, glob)
      if (!component) {
        // Fail loud but don't crash the whole tree — a single bad component string
        // shouldn't sink every other route. (flow/web console.errors and returns here too.)
        console.error(
          `[dynamicRoutes] unresolved component "${node.component}" for route "${node.name}" — skipped`,
        )
      } else {
        const relativePath = String(node.path).replace(/^\/+/, '')
        out.push({
          path: relativePath,
          name: node.name,
          component,
          // param routes pass params to the view as props (keeps SkillDetailView.vue's
          // existing `props: true` contract working).
          props: relativePath.includes(':'),
          meta: {
            title: node.title,
            icon: node.icon || '',
            keepalive: Boolean(node.keepalive),
            menu_type: node.menu_type,
            type: node.type,
            extend: node.extend || '',
            ruleCode: node.ruleCode || '',
          },
        })
      }
    }
    if (node.children && node.children.length) {
      buildRouteRecords(node.children, glob, out)
    }
  }
  return out
}

/**
 * Build the hierarchical navigation tree (visible menu items only). Hidden nodes
 * (add_rules_only) and button nodes are dropped; a hidden node's visible children (rare) are
 * hoisted so they aren't lost.
 *
 * @param {MenuNode[]} nodes
 * @returns {Array<{name:string,title:string,path:string,icon:string,type:string,children:Array}>}
 */
export function buildNavTree(nodes) {
  const result = []
  for (const node of nodes || []) {
    if (node.type === 'button') continue
    const children = node.children && node.children.length ? buildNavTree(node.children) : []
    if (!isNavVisible(node)) {
      result.push(...children) // hoist any visible descendants of a hidden node
      continue
    }
    result.push({
      name: node.name,
      title: node.title,
      path: node.path,
      icon: node.icon || '',
      type: node.type,
      children,
    })
  }
  return result
}

/**
 * Collect the set of granted permission (rule) codes from the pruned menu tree — both
 * `button` nodes and any node carrying a ruleCode. Used for in-page action gating
 * (e.g. "skillify:upload"); it is a UI convenience, never a security boundary (§11).
 *
 * @param {MenuNode[]} nodes
 * @param {Set<string>} [out]
 * @returns {Set<string>}
 */
export function buildAuthNode(nodes, out = new Set()) {
  for (const node of nodes || []) {
    if (node.ruleCode) out.add(node.ruleCode)
    if (node.children && node.children.length) buildAuthNode(node.children, out)
  }
  return out
}

/**
 * Register route records under the layout route, replacing any existing same-named route.
 * @returns {string[]} the names of the routes registered (for later removal)
 */
export function registerDynamicRoutes(router, records, parentName = LAYOUT_ROUTE_NAME) {
  const names = []
  for (const rec of records) {
    if (router.hasRoute(rec.name)) router.removeRoute(rec.name)
    router.addRoute(parentName, rec)
    names.push(rec.name)
  }
  return names
}

/** Remove previously-registered dynamic routes by name (logout / re-login). */
export function removeDynamicRoutes(router, names) {
  for (const name of names || []) {
    if (router.hasRoute(name)) router.removeRoute(name)
  }
}

/**
 * One-shot: turn a backend menu tree into registered routes + nav tree + authNode.
 * @returns {{registeredRouteNames:string[], navTree:Array, authNode:string[]}}
 */
export function generateRoutes(router, menus, glob = viewModules) {
  const records = buildRouteRecords(menus, glob)
  const registeredRouteNames = registerDynamicRoutes(router, records)
  return {
    registeredRouteNames,
    navTree: buildNavTree(menus),
    authNode: [...buildAuthNode(menus)],
  }
}
