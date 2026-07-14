import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/layouts/AppLayout.vue', import.meta.url), 'utf8')

describe('AppLayout shell contract', () => {
  it('composes the dedicated header, main content, and footer', () => {
    expect(source).toContain('<AppHeader')
    expect(source).toContain('<main class="app-main">')
    expect(source).toContain('<AppFooter')
    expect(source).toContain(':nav-items="menu.navTree"')
    expect(source).toContain('@logout="handleLogout"')
  })

  it('keeps short pages full height with a flexible main region', () => {
    expect(source).toContain('min-height: 100vh')
    expect(source).toMatch(/\.app-main\s*\{[^}]*flex:\s*1/s)
    expect(source).toMatch(/max-width:\s*1320px/)
  })
})
