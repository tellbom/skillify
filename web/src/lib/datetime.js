// zh-CN date/time formatting, replacing bare `.toLocaleString()/.toLocaleDateString()` calls
// scattered across views (docs/frontend-i18n-and-auth-module-plan.md §3.1). Single-locale
// (D3) for now; `locale` param kept so this doesn't need reshaping if a second locale is added.
export function formatDateTime(value, locale = 'zh-CN') {
  if (!value) return ''
  return new Date(value).toLocaleString(locale)
}

export function formatDate(value, locale = 'zh-CN') {
  if (!value) return ''
  return new Date(value).toLocaleDateString(locale)
}
