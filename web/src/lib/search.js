// Pure helpers for the C-4 search/filter/sort/pagination UI (SkillListView.vue). Kept separate
// from the component so the query-param assembly and pagination-state logic are unit-testable
// without mounting Vue (see web/src/lib/versions.js for the pattern this follows).
//
// Backend contract (Task 9, confirmed): GET /api/skills and GET /api/search both accept q,
// namespace, author, tags (comma-separated, AND semantics), sort ("installs"|"rating"|"updated",
// default "updated"), page (1-indexed, default 1), pageSize (default 20). Response is
// {items, total, page, pageSize} instead of a bare array.

export const SORT_OPTIONS = ['updated', 'installs', 'rating']
export const DEFAULT_SORT = 'updated'
export const DEFAULT_PAGE_SIZE = 20

/**
 * Build the params object passed to listSkills()/request() from raw filter-panel state.
 * Trims text fields, splits the comma/space-separated tags input into a clean `tags` string
 * (re-joined with commas, matching the backend's expected format), and drops any field that
 * ends up empty so request() omits it from the query string entirely (same "absent filter"
 * semantics as before this feature existed).
 * @param {{namespace?: string, author?: string, tagsInput?: string, sort?: string, page?: number, pageSize?: number}} state
 */
export function buildSearchParams(state = {}) {
  const namespace = (state.namespace || '').trim()
  const author = (state.author || '').trim()
  const tags = splitTagsInput(state.tagsInput).join(',')
  const sort = normalizeSort(state.sort)
  const page = normalizePage(state.page)
  const pageSize = state.pageSize || undefined

  const params = { namespace, author, tags, sort, page, pageSize }
  for (const key of Object.keys(params)) {
    if (params[key] === '' || params[key] === undefined || params[key] === null) delete params[key]
  }
  return params
}

/** Split a free-text tags input (comma and/or whitespace separated) into a deduped, trimmed list. */
export function splitTagsInput(tagsInput) {
  if (!tagsInput) return []
  return [...new Set(tagsInput.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean))]
}

/** Fall back to the default sort when given an unrecognized value, rather than sending garbage. */
export function normalizeSort(sort) {
  return SORT_OPTIONS.includes(sort) ? sort : DEFAULT_SORT
}

/** Clamp page to a positive integer, defaulting to 1 for missing/invalid input. */
export function normalizePage(page) {
  const n = Number(page)
  return Number.isInteger(n) && n >= 1 ? n : 1
}

/**
 * Given the previous and next values of the six reactive sources SkillListView watches together
 * (`[query, namespace, author, tagsInput, sort, page]`, in that order), decide how to react to a
 * single batched change. Used by a single `watch()` covering all six sources so that N
 * simultaneous ref mutations in one tick (e.g. `clearFilters()` resetting namespace/author/
 * tagsInput/sort/page all at once) resolve to exactly one action instead of one `load()` per
 * independent watcher. See SkillListView.vue for how the result is applied.
 *
 * - Only `page` changed: load immediately, no page reset, no debounce (that's just prev/next).
 * - `sort` changed (alone or together with anything else, e.g. clearFilters therefore counts as
 *   this case): reset to page 1 and load immediately — a deliberate, discrete user action, not
 *   free text the user might still be typing.
 * - Only text filters (`query`/`namespace`/`author`/`tagsInput`) changed: reset to page 1, but
 *   debounced, so rapid typing doesn't fire a request per keystroke.
 * - Nothing changed (e.g. initial call before any real diff): no-op.
 *
 * @param {[string, string, string, string, string, number]} prev
 * @param {[string, string, string, string, string, number]} next
 * @returns {{action: 'none'|'load'|'resetImmediate'|'resetDebounced'}}
 */
export function resolveFilterChange(prev, next) {
  const [pQuery, pNamespace, pAuthor, pTags, pSort, pPage] = prev || []
  const [nQuery, nNamespace, nAuthor, nTags, nSort, nPage] = next || []

  const textChanged = pQuery !== nQuery || pNamespace !== nNamespace || pAuthor !== nAuthor || pTags !== nTags
  const sortChanged = pSort !== nSort
  const pageChanged = pPage !== nPage

  if (!textChanged && !sortChanged && !pageChanged) return { action: 'none' }
  if (sortChanged) return { action: 'resetImmediate' }
  if (textChanged) return { action: 'resetDebounced' }
  return { action: 'load' }
}

/**
 * Derive pagination display state from a SearchResult ({items, total, page, pageSize}).
 * `totalPages` is at least 1 even when total is 0, so a "page 1 of 1" UI never divides by zero.
 * @param {{total?: number, page?: number, pageSize?: number}} result
 */
export function paginationState(result = {}) {
  const page = normalizePage(result.page)
  const pageSize = result.pageSize || DEFAULT_PAGE_SIZE
  const total = result.total || 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  return {
    page,
    pageSize,
    total,
    totalPages,
    hasPrev: page > 1,
    hasNext: page < totalPages,
  }
}
