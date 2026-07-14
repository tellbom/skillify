// Pure display-formatting helpers for the home/detail page redesign (see docs prototype at
// web/temp/Skillify Platform Interface Design/Skillify.dc.html). Kept separate from the
// components so they're unit-testable without mounting Vue (see web/src/lib/versions.js for the
// pattern this follows).

/**
 * Abbreviate a count for compact stat displays (prototype's `_fmt`): values under 1000 are shown
 * as-is; values at or above 1000 are shown as "12.8k" (one decimal place, trailing ".0" dropped).
 * @param {number} n
 */
export function formatCount(n) {
  const value = Number(n) || 0
  if (value < 1000) return String(value)
  const abbreviated = (value / 1000).toFixed(1).replace(/\.0$/, '')
  return `${abbreviated}k`
}

/**
 * Keep rating displays aligned while preserving the API's `null` = no ratings semantics.
 * @param {number|null|undefined} value
 */
export function formatRating(value) {
  if (value == null) return '—'
  return Number(value).toFixed(1)
}

/**
 * Relative day-count label for a date (prototype's `_daysText`): "今天" for today, "昨天" for
 * yesterday, otherwise "N 天前". `now` is injectable for deterministic tests instead of relying
 * on the implicit system clock.
 * @param {string} dateStr
 * @param {{now?: Date}} [options]
 */
export function formatRelativeDays(dateStr, { now } = {}) {
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  const reference = now || new Date()

  const startOf = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const days = Math.round((startOf(reference) - startOf(date)) / 86400000)

  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  return `${days} 天前`
}
