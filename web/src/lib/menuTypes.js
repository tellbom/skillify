// Route-metadata contract consumed from Rbac.Api's `GET /api/admin/index`.
//
// Deliberately the SAME vocabulary flow/web (E:\Web\flow\web) emits — see
// docs/frontend-dynamic-routing-migration.md §5 (user decision 2026-07-10: "flow/web's real
// vocabulary"). No `hidden`/`activeMenu` fields: a routable-but-not-in-nav page (e.g. the
// skill detail page) is expressed via `extend: 'add_rules_only'`, exactly as flow does.
//
// This is a plain-JS project, so the contract lives as JSDoc typedefs (no TypeScript).

/**
 * @typedef {Object} MenuNode
 * @property {string}  [id]
 * @property {string}  [pid]                 parent id ("0" for root) — drives nav nesting
 * @property {string}  title                 display name in navigation
 * @property {string}  name                  unique vue-router route name
 * @property {string}  path                  route path; may contain :params (see §7)
 * @property {string}  [icon]
 * @property {'menu_dir'|'menu'|'button'} type
 *           menu_dir = nav grouping (no route); menu = page (route); button = permission-only
 * @property {'tab'|'link'|'iframe'} [menu_type] tab = normal page; iframe/link reserved
 * @property {string}  [url]
 * @property {string}  [component]           MUST equal an import.meta.glob key, e.g.
 *                                           "/src/views/SkillListView.vue"
 * @property {''|'add_menu_only'|'add_rules_only'} [extend]
 *           '' = route + nav; add_menu_only = nav only (no route);
 *           add_rules_only = route only, HIDDEN from nav (our "hidden route")
 * @property {boolean} [keepalive]
 * @property {string}  [permissionCode]
 * @property {string}  [ruleCode]            action permission code, e.g. "skillify:upload"
 * @property {MenuNode[]} [children]
 */

/**
 * @typedef {Object} BackendIndexResult
 * @property {Object}     adminInfo   { id, userid, username, super, project }
 * @property {MenuNode[]} menus       menu tree, already pruned per-user by the backend
 * @property {string}     [routePath] default landing route after login
 */

export {}
