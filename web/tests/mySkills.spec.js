import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { installCountFor, retryQueryFor } from '../src/lib/mySkills.js'
import { getMySkills, getMyNamespaces, getMyPublishJobs, getMyUsage } from '../src/lib/api.js'

describe('installCountFor', () => {
  it('looks up the count by "namespace/name" key', () => {
    const usage = { totalSkills: 2, totalInstalls: 7, installsBySkill: { 'acme/pivot': 5, 'acme/other': 2 } }
    expect(installCountFor(usage, { namespace: 'acme', name: 'pivot' })).toBe(5)
  })

  it('defaults to 0 when the skill has no recorded installs', () => {
    const usage = { totalSkills: 1, totalInstalls: 0, installsBySkill: {} }
    expect(installCountFor(usage, { namespace: 'acme', name: 'pivot' })).toBe(0)
  })

  it('defaults to 0 when usage data has not loaded yet (null)', () => {
    expect(installCountFor(null, { namespace: 'acme', name: 'pivot' })).toBe(0)
  })

  it('defaults to 0 when installsBySkill is missing from the payload', () => {
    expect(installCountFor({ totalSkills: 0, totalInstalls: 0 }, { namespace: 'acme', name: 'pivot' })).toBe(0)
  })
})

describe('retryQueryFor', () => {
  it('maps a failed publish job to retry query params', () => {
    const job = { namespace: 'acme', name: 'pivot', version: '1.2.0', status: 'failed' }
    expect(retryQueryFor(job)).toEqual({
      retryNamespace: 'acme',
      retryName: 'pivot',
      retryVersion: '1.2.0',
    })
  })
})

describe('api.js my-skills query assembly', () => {
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

  it('getMySkills hits /my/skills', async () => {
    await getMySkills()
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/my/skills')
  })

  it('getMyNamespaces hits /my/namespaces', async () => {
    await getMyNamespaces()
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/my/namespaces')
  })

  it('getMyPublishJobs defaults to no status param (backend defaults to "failed")', async () => {
    await getMyPublishJobs()
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/my/publish-jobs')
    expect(url.searchParams.has('status')).toBe(false)
  })

  it('getMyPublishJobs passes status through as a query param', async () => {
    await getMyPublishJobs('all')
    const url = fetchMock.mock.calls[0][0]
    expect(url.searchParams.get('status')).toBe('all')
  })

  it('getMyUsage hits /my/usage', async () => {
    await getMyUsage()
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/my/usage')
  })
})
