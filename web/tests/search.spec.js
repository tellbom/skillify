import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  buildSearchParams,
  splitTagsInput,
  normalizeSort,
  normalizePage,
  paginationState,
  resolveFilterChange,
  activeFilterChips,
  SORT_OPTIONS,
  DEFAULT_SORT,
  DEFAULT_PAGE_SIZE,
} from '../src/lib/search.js'
import { listSkills } from '../src/lib/api.js'

describe('splitTagsInput', () => {
  it('splits on commas and whitespace, trims, and dedupes', () => {
    expect(splitTagsInput('ai, cli  ai,  excel')).toEqual(['ai', 'cli', 'excel'])
  })

  it('handles empty/missing input', () => {
    expect(splitTagsInput('')).toEqual([])
    expect(splitTagsInput(undefined)).toEqual([])
  })

  it('ignores stray separators', () => {
    expect(splitTagsInput(' , ai ,, cli ')).toEqual(['ai', 'cli'])
  })
})

describe('normalizeSort', () => {
  it('accepts known sort values', () => {
    for (const s of SORT_OPTIONS) expect(normalizeSort(s)).toBe(s)
  })

  it('falls back to the default for unknown/missing values', () => {
    expect(normalizeSort('bogus')).toBe(DEFAULT_SORT)
    expect(normalizeSort(undefined)).toBe(DEFAULT_SORT)
    expect(normalizeSort(null)).toBe(DEFAULT_SORT)
  })
})

describe('normalizePage', () => {
  it('passes through valid positive integers', () => {
    expect(normalizePage(1)).toBe(1)
    expect(normalizePage(5)).toBe(5)
  })

  it('defaults to 1 for invalid/missing values', () => {
    expect(normalizePage(0)).toBe(1)
    expect(normalizePage(-3)).toBe(1)
    expect(normalizePage(1.5)).toBe(1)
    expect(normalizePage('abc')).toBe(1)
    expect(normalizePage(undefined)).toBe(1)
  })
})

describe('buildSearchParams', () => {
  it('trims namespace/author and joins tags back into a comma string', () => {
    const params = buildSearchParams({
      namespace: '  excel-team  ',
      author: ' alice ',
      tagsInput: 'ai, cli',
      sort: 'installs',
      page: 2,
    })
    expect(params).toEqual({
      namespace: 'excel-team',
      author: 'alice',
      tags: 'ai,cli',
      sort: 'installs',
      page: 2,
    })
  })

  it('omits empty fields entirely rather than sending blanks', () => {
    const params = buildSearchParams({})
    expect(params).toEqual({ sort: DEFAULT_SORT, page: 1 })
  })

  it('normalizes an invalid sort/page instead of passing them through', () => {
    const params = buildSearchParams({ sort: 'bogus', page: -1 })
    expect(params.sort).toBe(DEFAULT_SORT)
    expect(params.page).toBe(1)
  })

  it('omits pageSize when not explicitly given', () => {
    const params = buildSearchParams({ page: 1 })
    expect(params).not.toHaveProperty('pageSize')
  })

  it('includes pageSize when given', () => {
    const params = buildSearchParams({ pageSize: 50 })
    expect(params.pageSize).toBe(50)
  })
})

describe('paginationState', () => {
  it('derives totalPages and hasPrev/hasNext from a SearchResult', () => {
    const state = paginationState({ total: 45, page: 2, pageSize: 20 })
    expect(state).toEqual({ page: 2, pageSize: 20, total: 45, totalPages: 3, hasPrev: true, hasNext: true })
  })

  it('clamps totalPages to at least 1 when there are zero results', () => {
    const state = paginationState({ total: 0, page: 1, pageSize: 20 })
    expect(state.totalPages).toBe(1)
    expect(state.hasPrev).toBe(false)
    expect(state.hasNext).toBe(false)
  })

  it('defaults sensibly when called with no argument (initial component state)', () => {
    const state = paginationState()
    expect(state).toEqual({ page: 1, pageSize: DEFAULT_PAGE_SIZE, total: 0, totalPages: 1, hasPrev: false, hasNext: false })
  })

  it('hasNext is false on the last page', () => {
    const state = paginationState({ total: 40, page: 2, pageSize: 20 })
    expect(state.hasNext).toBe(false)
    expect(state.hasPrev).toBe(true)
  })
})

describe('resolveFilterChange (C-4 single-watcher reload consolidation)', () => {
  // Tuple shape: [query, namespace, author, tagsInput, sort, page]
  const base = ['', '', '', '', 'updated', 1]

  it('does nothing when nothing actually changed', () => {
    expect(resolveFilterChange(base, [...base])).toEqual({ action: 'none' })
  })

  it('loads immediately when only page changed (prev/next buttons)', () => {
    const next = [...base]
    next[5] = 2
    expect(resolveFilterChange(base, next)).toEqual({ action: 'load' })
  })

  it('resets immediately (no debounce) when sort changed', () => {
    const next = [...base]
    next[4] = 'installs'
    expect(resolveFilterChange(base, next)).toEqual({ action: 'resetImmediate' })
  })

  it('debounces when only a text filter changed', () => {
    const next = [...base]
    next[1] = 'excel-team' // namespace
    expect(resolveFilterChange(base, next)).toEqual({ action: 'resetDebounced' })

    const queryNext = [...base]
    queryNext[0] = 'hello'
    expect(resolveFilterChange(base, queryNext)).toEqual({ action: 'resetDebounced' })
  })

  it('treats a clearFilters()-style batch (text + sort + page all change at once) as a single immediate reset', () => {
    // Mirrors clearFilters(): namespace/author/tagsInput/sort/page all reset together in one tick.
    const prev = ['', 'excel-team', 'alice', 'ai,cli', 'installs', 3]
    const next = ['', '', '', '', 'updated', 1]
    expect(resolveFilterChange(prev, next)).toEqual({ action: 'resetImmediate' })
  })

  it('sort change takes priority over a simultaneous text-filter change (does not debounce)', () => {
    const prev = ['', 'ns', '', '', 'updated', 1]
    const next = ['', 'ns2', '', '', 'installs', 1]
    expect(resolveFilterChange(prev, next)).toEqual({ action: 'resetImmediate' })
  })
})

describe('activeFilterChips', () => {
  it('returns one chip per non-empty scalar filter', () => {
    const chips = activeFilterChips({ query: 'excel', namespace: 'ns', author: 'alice', tagsInput: '' })
    expect(chips).toEqual([
      { type: 'query', label: 'excel', value: 'excel' },
      { type: 'namespace', label: 'ns', value: 'ns' },
      { type: 'author', label: 'alice', value: 'alice' },
    ])
  })

  it('explodes tagsInput into one chip per tag', () => {
    const chips = activeFilterChips({ tagsInput: 'ai, cli' })
    expect(chips).toEqual([
      { type: 'tag', label: 'ai', value: 'ai' },
      { type: 'tag', label: 'cli', value: 'cli' },
    ])
  })

  it('trims whitespace and omits blank filters', () => {
    expect(activeFilterChips({ query: '  ', namespace: '  ns  ' })).toEqual([
      { type: 'namespace', label: 'ns', value: 'ns' },
    ])
  })

  it('returns an empty array when nothing is active', () => {
    expect(activeFilterChips({})).toEqual([])
    expect(activeFilterChips()).toEqual([])
  })
})

describe('api.js listSkills query assembly (C-4 filters/sort/pagination)', () => {
  let fetchMock

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [], total: 0, page: 1, pageSize: 20 }),
    })
    vi.stubGlobal('fetch', fetchMock)
    // No jsdom in this project's vitest config (node env) — api.js's `request()` reads
    // `window.location.origin` to resolve its relative API_BASE, so stub the minimal shape.
    vi.stubGlobal('window', { location: { origin: 'http://localhost' } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hits /skills (not /search) when query is empty', async () => {
    await listSkills('', { sort: 'updated', page: 1 })
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/skills')
    expect(url.searchParams.has('q')).toBe(false)
  })

  it('hits /search when a query is given, carrying q plus filter params', async () => {
    await listSkills('excel', { namespace: 'ns', author: 'bob', tags: 'ai,cli', sort: 'installs', page: 2 })
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/search')
    expect(url.searchParams.get('q')).toBe('excel')
    expect(url.searchParams.get('namespace')).toBe('ns')
    expect(url.searchParams.get('author')).toBe('bob')
    expect(url.searchParams.get('tags')).toBe('ai,cli')
    expect(url.searchParams.get('sort')).toBe('installs')
    expect(url.searchParams.get('page')).toBe('2')
  })

  it('resolves to the SearchResult wrapper shape, not a bare array', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ items: [{ namespace: 'ns', name: 'skill' }], total: 1, page: 1, pageSize: 20 }),
    })
    const result = await listSkills('')
    expect(result).toEqual({ items: [{ namespace: 'ns', name: 'skill' }], total: 1, page: 1, pageSize: 20 })
  })

  it('omits filter params that are absent', async () => {
    await listSkills('')
    const url = fetchMock.mock.calls[0][0]
    expect(url.searchParams.has('namespace')).toBe(false)
    expect(url.searchParams.has('author')).toBe(false)
    expect(url.searchParams.has('tags')).toBe(false)
  })
})
