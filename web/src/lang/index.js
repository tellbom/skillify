import { createI18n } from 'vue-i18n'
import elementZhCnLocale from 'element-plus/es/locale/lang/zh-cn'
import { useLocaleStore } from '../stores/locale.js'

// Ported from E:\Web\flow\web\src\lang\index.ts (loadLang/editDefaultLang), collapsed to
// Skillify's single-locale (zh-cn only, D3) case: no backend/frontend namespace split, no
// per-locale glob switch. See docs/frontend-i18n-and-auth-module-plan.md §3.1.
export let i18n

// Each ./zh-cn/<name>.js becomes messages['zh-cn'][<name>] (e.g. skills.js -> t('skills.x')).
const pageModules = import.meta.glob('./zh-cn/*.js', { eager: true })

export async function loadLang(app) {
  const localeStore = useLocaleStore()
  const locale = localeStore.defaultLang

  const messages = { [locale]: { ...elementZhCnLocale } }
  for (const path in pageModules) {
    const name = path.replace('./zh-cn/', '').replace(/\.js$/, '')
    messages[locale][name] = pageModules[path].default
  }

  i18n = createI18n({
    legacy: false,
    globalInjection: true,
    locale,
    fallbackLocale: localeStore.fallbackLang,
    messages,
  })

  app.use(i18n)
  return i18n
}

/** Switch the active locale and reload (language packs load eagerly per session, same as
 * flow/web's editDefaultLang — no hot-swap). Only 'zh-cn' exists today (D3); kept for parity
 * so adding a second locale later doesn't require reshaping this module. */
export function editDefaultLang(lang) {
  const localeStore = useLocaleStore()
  localeStore.setLang(lang)
  location.reload()
}
