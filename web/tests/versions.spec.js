import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { sortVersionsDesc, groupDiff, isDiffEmpty } from '../src/lib/versions.js'
import { getSkillDetail, getVersions, getVersionDiff, yankVersion, unyankVersion } from '../src/lib/api.js'

describe('sortVersionsDesc', () => {
  it('sorts versions newest-published-first', () => {
    const versions = [
      { version: '1.0.0', publishedAt: '2026-01-01T00:00:00Z', yanked: false, releaseNotes: null },
      { version: '1.2.0', publishedAt: '2026-03-01T00:00:00Z', yanked: false, releaseNotes: null },
      { version: '1.1.0', publishedAt: '2026-02-01T00:00:00Z', yanked: true, releaseNotes: 'fix' },
    ]
    expect(sortVersionsDesc(versions).map((v) => v.version)).toEqual(['1.2.0', '1.1.0', '1.0.0'])
  })

  it('does not mutate the input array', () => {
    const versions = [
      { version: '1.0.0', publishedAt: '2026-01-01T00:00:00Z' },
      { version: '2.0.0', publishedAt: '2026-02-01T00:00:00Z' },
    ]
    const copy = [...versions]
    sortVersionsDesc(versions)
    expect(versions).toEqual(copy)
  })

  it('falls back to version-string comparison when publishedAt is unparseable', () => {
    const versions = [
      { version: '1.0.0', publishedAt: 'not-a-date' },
      { version: '2.0.0', publishedAt: 'also-not-a-date' },
    ]
    expect(sortVersionsDesc(versions).map((v) => v.version)).toEqual(['2.0.0', '1.0.0'])
  })

  it('handles an empty/missing list', () => {
    expect(sortVersionsDesc([])).toEqual([])
    expect(sortVersionsDesc(undefined)).toEqual([])
  })
})

describe('groupDiff', () => {
  it('sorts each group alphabetically and defaults missing groups to []', () => {
    const diff = { added: ['b.md', 'a.md'], removed: ['z.txt'] }
    expect(groupDiff(diff)).toEqual({ added: ['a.md', 'b.md'], removed: ['z.txt'], modified: [] })
  })

  it('handles an undefined diff', () => {
    expect(groupDiff(undefined)).toEqual({ added: [], removed: [], modified: [] })
  })
})

describe('isDiffEmpty', () => {
  it('is true when all three groups are empty', () => {
    expect(isDiffEmpty({ added: [], removed: [], modified: [] })).toBe(true)
    expect(isDiffEmpty({})).toBe(true)
    expect(isDiffEmpty(undefined)).toBe(true)
  })

  it('is false when any group has entries', () => {
    expect(isDiffEmpty({ added: ['a.md'], removed: [], modified: [] })).toBe(false)
  })
})

describe('api.js version-center query assembly', () => {
  let fetchMock

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({}),
    })
    vi.stubGlobal('fetch', fetchMock)
    // No jsdom in this project's vitest config (node env) — api.js's `request()` reads
    // `window.location.origin` to resolve its relative API_BASE, so stub the minimal shape.
    vi.stubGlobal('window', { location: { origin: 'http://localhost' } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('getSkillDetail omits the version query param when not given', async () => {
    await getSkillDetail('excel', 'pivot')
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/skills/excel/pivot')
    expect(url.searchParams.has('version')).toBe(false)
  })

  it('getSkillDetail passes version through as a query param', async () => {
    await getSkillDetail('excel', 'pivot', '1.2.0')
    const url = fetchMock.mock.calls[0][0]
    expect(url.searchParams.get('version')).toBe('1.2.0')
  })

  it('getVersions hits the /versions endpoint', async () => {
    await getVersions('excel', 'pivot')
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/versions')
  })

  it('getVersionDiff sends from/to as query params', async () => {
    await getVersionDiff('excel', 'pivot', '1.0.0', '2.0.0')
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/diff')
    expect(url.searchParams.get('from')).toBe('1.0.0')
    expect(url.searchParams.get('to')).toBe('2.0.0')
  })

  it('yankVersion POSTs to the yank endpoint', async () => {
    await yankVersion('excel', 'pivot', '1.0.0')
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/versions/1.0.0/yank')
    expect(opts.method).toBe('POST')
  })

  it('unyankVersion POSTs to the unyank endpoint', async () => {
    await unyankVersion('excel', 'pivot', '1.0.0')
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skills/excel/pivot/versions/1.0.0/unyank')
    expect(opts.method).toBe('POST')
  })
})
