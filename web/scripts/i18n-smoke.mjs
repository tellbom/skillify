// N6.2 (docs/frontend-i18n-auth-task-book.md): i18n smoke test over the framework-level
// static pages (login/404/401/403). These bypass the auth guard entirely (see
// router/guard.js's FRAMEWORK_ROUTE_NAMES check), so they're safe to exercise without a real
// Keycloak/Rbac.Api backend reachable from this environment. Deep RBAC/auth-module flows are
// N6.3, explicitly blocked on external RBAC test-network data (same status as
// docs/frontend-dynamic-routing-migration.md's existing blocked items).
//
// Uses the `playwright` library directly (not the `@playwright/test` runner, which isn't a
// project dependency).
//
// Usage: start the dev server yourself first (auto-spawning it from this script proved
// unreliable in this sandbox — orphaned child processes on Windows), then run this script:
//   node_modules/.bin/vite --port 4173 --strictPort --host 127.0.0.1 &
//   node scripts/i18n-smoke.mjs
import { chromium } from 'playwright'

const BASE = 'http://127.0.0.1:4173'

const checks = [
  {
    path: '/login',
    expect: ['Skillify', '内部技能目录'],
    expectOneOf: ['使用 Keycloak 登录', 'Keycloak 未在此部署中配置'],
  },
  { path: '/404', expect: ['404', '此页面不存在', '返回 Skillify'] },
  { path: '/401', expect: ['无访问权限'] },
  { path: '/403', expect: ['会话已过期', '登录'] },
]

async function main() {
  const browser = await chromium.launch()
  const page = await browser.newPage()
  const results = []

  for (const check of checks) {
    await page.goto(BASE + check.path, { waitUntil: 'networkidle', timeout: 15_000 })
    const bodyText = await page.textContent('body')
    const missing = (check.expect || []).filter((s) => !bodyText.includes(s))
    const oneOfOk = !check.expectOneOf || check.expectOneOf.some((s) => bodyText.includes(s))
    const pass = missing.length === 0 && oneOfOk
    results.push({ path: check.path, pass, missing, bodyText: bodyText.slice(0, 300) })
  }

  await browser.close()

  let allPass = true
  for (const r of results) {
    console.log(`${r.pass ? 'PASS' : 'FAIL'} ${r.path}${r.missing?.length ? ` missing: ${r.missing.join(', ')}` : ''}`)
    if (!r.pass) {
      allPass = false
      console.log(`  body snippet: ${r.bodyText}`)
    }
  }
  process.exit(allPass ? 0 : 1)
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
