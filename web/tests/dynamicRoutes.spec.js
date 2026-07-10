import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import {
  buildRouteRecords,
  buildNavTree,
  buildAuthNode,
  generateRoutes,
  removeDynamicRoutes,
  resolveComponent,
} from '../src/router/dynamicRoutes.js'
import { LAYOUT_ROUTE_NAME } from '../src/router/constants.js'

// Fixture glob — mirrors import.meta.glob's shape (path -> lazy importer). Fixtures exist
// ONLY in this test; they never run in the app (user decision 2026-07-10).
const GLOB = {
  '/src/views/SkillListView.vue': () => Promise.resolve({ default: { name: 'SkillListView' } }),
  '/src/views/SkillDetailView.vue': () => Promise.resolve({ default: { name: 'SkillDetailView' } }),
  '/src/views/UploadView.vue': () => Promise.resolve({ default: { name: 'UploadView' } }),
  '/src/views/LeaderboardView.vue': () => Promise.resolve({ default: { name: 'LeaderboardView' } }),
}

// The canonical Skillify menu tree from docs/frontend-dynamic-routing-migration.md §6,
// in flow/web's real vocabulary (type/menu_type/extend).
function skillifyMenus() {
  return [
    {
      id: '1', pid: '0', title: '技能市场', name: 'skills', path: '/',
      type: 'menu', menu_type: 'tab', extend: '',
      component: '/src/views/SkillListView.vue',
      children: [
        {
          id: '2', pid: '1', title: '技能详情', name: 'skill-detail',
          path: '/skills/:namespace/:name',
          type: 'menu', menu_type: 'tab', extend: 'add_rules_only', // hidden route
          component: '/src/views/SkillDetailView.vue',
        },
      ],
    },
    {
      id: '3', pid: '0', title: '上传技能', name: 'upload', path: '/upload',
      type: 'menu', menu_type: 'tab', extend: '',
      component: '/src/views/UploadView.vue', ruleCode: 'skillify:upload',
    },
    {
      id: '4', pid: '0', title: '排行榜', name: 'leaderboard', path: '/leaderboard',
      type: 'menu', menu_type: 'tab', extend: '',
      component: '/src/views/LeaderboardView.vue',
    },
    {
      id: '5', pid: '0', title: '上传', name: 'perm-upload', path: '',
      type: 'button', ruleCode: 'skillify:upload',
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

describe('resolveComponent', () => {
  it('returns the importer for a known component string', () => {
    expect(resolveComponent('/src/views/UploadView.vue', GLOB)).toBe(GLOB['/src/views/UploadView.vue'])
  })
  it('returns null for an unknown component string', () => {
    expect(resolveComponent('/src/views/Nope.vue', GLOB)).toBeNull()
  })
})

describe('buildRouteRecords', () => {
  it('creates one route per tab page, skipping button nodes', () => {
    const records = buildRouteRecords(skillifyMenus(), GLOB)
    const names = records.map((r) => r.name).sort()
    expect(names).toEqual(['leaderboard', 'skill-detail', 'skills', 'upload'])
    expect(names).not.toContain('perm-upload') // button node → no route
  })

  it('makes child paths relative to the layout ("/" -> "", "/upload" -> "upload")', () => {
    const byName = Object.fromEntries(buildRouteRecords(skillifyMenus(), GLOB).map((r) => [r.name, r]))
    expect(byName.skills.path).toBe('') // index child
    expect(byName.upload.path).toBe('upload')
    expect(byName.leaderboard.path).toBe('leaderboard')
    expect(byName['skill-detail'].path).toBe('skills/:namespace/:name')
  })

  it('sets props:true only on param routes', () => {
    const byName = Object.fromEntries(buildRouteRecords(skillifyMenus(), GLOB).map((r) => [r.name, r]))
    expect(byName['skill-detail'].props).toBe(true)
    expect(byName.upload.props).toBe(false)
  })

  it('carries flow vocabulary through meta (extend/menu_type/type/ruleCode)', () => {
    const byName = Object.fromEntries(buildRouteRecords(skillifyMenus(), GLOB).map((r) => [r.name, r]))
    expect(byName['skill-detail'].meta.extend).toBe('add_rules_only')
    expect(byName.upload.meta.ruleCode).toBe('skillify:upload')
    expect(byName.skills.meta.menu_type).toBe('tab')
  })

  it('skips (does not throw on) an unresolved component and logs an error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const menus = [
      { name: 'ghost', path: '/ghost', type: 'menu', menu_type: 'tab', extend: '', component: '/src/views/Ghost.vue' },
      { name: 'upload', path: '/upload', type: 'menu', menu_type: 'tab', extend: '', component: '/src/views/UploadView.vue' },
    ]
    const records = buildRouteRecords(menus, GLOB)
    expect(records.map((r) => r.name)).toEqual(['upload'])
    expect(spy).toHaveBeenCalledOnce()
    spy.mockRestore()
  })

  it('does not create routes for add_menu_only or iframe nodes', () => {
    const menus = [
      { name: 'dir', path: '/dir', type: 'menu', menu_type: 'tab', extend: 'add_menu_only', component: '/src/views/UploadView.vue' },
      { name: 'frame', path: '/frame', type: 'menu', menu_type: 'iframe', extend: '', url: 'http://x' },
    ]
    expect(buildRouteRecords(menus, GLOB)).toEqual([])
  })
})

describe('buildNavTree', () => {
  it('shows normal pages but hides add_rules_only and button nodes', () => {
    const nav = buildNavTree(skillifyMenus())
    const topNames = nav.map((n) => n.name).sort()
    expect(topNames).toEqual(['leaderboard', 'skills', 'upload'])
    // skill-detail is hidden (add_rules_only), not nested under skills either
    expect(nav.find((n) => n.name === 'skills').children).toEqual([])
    expect(nav.find((n) => n.name === 'perm-upload')).toBeUndefined()
  })
})

describe('buildAuthNode', () => {
  it('collects granted rule codes from button and menu nodes', () => {
    const set = buildAuthNode(skillifyMenus())
    expect(set.has('skillify:upload')).toBe(true)
  })
})

describe('generateRoutes / removeDynamicRoutes (real router)', () => {
  let router
  beforeEach(() => {
    router = makeRouter()
  })

  it('registers all business routes under the layout and reports their names', () => {
    const { registeredRouteNames, navTree, authNode } = generateRoutes(router, skillifyMenus(), GLOB)
    expect(registeredRouteNames.sort()).toEqual(['leaderboard', 'skill-detail', 'skills', 'upload'])
    expect(router.hasRoute('skills')).toBe(true)
    expect(router.hasRoute('upload')).toBe(true)
    expect(router.hasRoute('skill-detail')).toBe(true)
    expect(navTree.map((n) => n.name).sort()).toEqual(['leaderboard', 'skills', 'upload'])
    expect(authNode).toContain('skillify:upload')
  })

  it('resolves "/" to the index (list) page and the hidden detail param route', async () => {
    generateRoutes(router, skillifyMenus(), GLOB)
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('skills')
    await router.push('/skills/excel/pivot')
    expect(router.currentRoute.value.name).toBe('skill-detail')
    expect(router.currentRoute.value.params).toMatchObject({ namespace: 'excel', name: 'pivot' })
  })

  it('removeDynamicRoutes leaves only the framework/static routes', () => {
    const { registeredRouteNames } = generateRoutes(router, skillifyMenus(), GLOB)
    removeDynamicRoutes(router, registeredRouteNames)
    expect(router.hasRoute('skills')).toBe(false)
    expect(router.hasRoute('upload')).toBe(false)
    expect(router.hasRoute('skill-detail')).toBe(false)
    expect(router.hasRoute(LAYOUT_ROUTE_NAME)).toBe(true) // static layout survives
    expect(router.hasRoute('login')).toBe(true)
  })
})
