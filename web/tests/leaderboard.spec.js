import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { getLeaderboard } from '../src/lib/api.js'

describe('api.js leaderboard query assembly (C-6 time window)', () => {
  let fetchMock

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    })
    vi.stubGlobal('fetch', fetchMock)
    // No jsdom in this project's vitest config (node env) — api.js's `request()` reads
    // `window.location.origin` to resolve its relative API_BASE, so stub the minimal shape.
    vi.stubGlobal('window', { location: { origin: 'http://localhost' } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends dimension and window as query params', async () => {
    await getLeaderboard('installs', 'week')
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/leaderboard')
    expect(url.searchParams.get('dimension')).toBe('installs')
    expect(url.searchParams.get('window')).toBe('week')
  })

  it('omits window when not given', async () => {
    await getLeaderboard('recent')
    const url = fetchMock.mock.calls[0][0]
    expect(url.searchParams.get('dimension')).toBe('recent')
    expect(url.searchParams.has('window')).toBe(false)
  })

  it('supports "month" and "all" window values', async () => {
    await getLeaderboard('installs', 'month')
    expect(fetchMock.mock.calls[0][0].searchParams.get('window')).toBe('month')

    await getLeaderboard('installs', 'all')
    expect(fetchMock.mock.calls[1][0].searchParams.get('window')).toBe('all')
  })
})
