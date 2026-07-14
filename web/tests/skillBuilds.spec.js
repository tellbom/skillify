import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  RUNTIME_OPTIONS,
  TARGET_OPTIONS,
  emptyManifestDraft,
  manifestDraftFrom,
  emptySkillMdDraft,
  parseSkillMd,
  composeSkillMd,
  isReservedBuildPath,
  isSafeRelativePath,
  dedupeList,
} from '../src/lib/skillBuilds.js'
import {
  createGuidedBuild,
  getSkillBuild,
  patchSkillBuild,
  addSkillBuildFile,
  deleteSkillBuildFile,
  publishSkillBuild,
  scanExternalSkill,
  selectExternalCandidates,
} from '../src/lib/api.js'

describe('RUNTIME_OPTIONS / TARGET_OPTIONS', () => {
  it('match manifest v1 enums (spec/skill-manifest-v1.md §3)', () => {
    expect(RUNTIME_OPTIONS).toEqual(['claude-agent-skill', 'custom'])
    expect(TARGET_OPTIONS).toEqual(['claude', 'opencode', 'codex', 'aider', 'project'])
  })
})

describe('emptyManifestDraft', () => {
  it('returns manifest v1 field names with blank values, not a separate schema', () => {
    expect(emptyManifestDraft()).toEqual({
      namespace: '',
      name: '',
      version: '',
      description: '',
      author: '',
      license: '',
      runtime: '',
      targets: [],
      dependencies: { python: [], system: [], skills: [] },
      permissions: [],
      tags: [],
    })
  })
})

describe('manifestDraftFrom', () => {
  it('fills a fully blank draft from an undefined manifest', () => {
    expect(manifestDraftFrom(undefined)).toEqual(emptyManifestDraft())
  })

  it('preserves provided fields and backfills missing ones', () => {
    const draft = manifestDraftFrom({ namespace: 'demo', name: 'hello-skill', tags: ['example'] })
    expect(draft.namespace).toBe('demo')
    expect(draft.name).toBe('hello-skill')
    expect(draft.tags).toEqual(['example'])
    expect(draft.version).toBe('')
    expect(draft.dependencies).toEqual({ python: [], system: [], skills: [] })
  })

  it('never shares array/object references with the source manifest', () => {
    const source = { tags: ['a'], dependencies: { python: ['requests'] } }
    const draft = manifestDraftFrom(source)
    draft.tags.push('b')
    draft.dependencies.python.push('flask')
    expect(source.tags).toEqual(['a'])
    expect(source.dependencies.python).toEqual(['requests'])
  })

  it('defaults only an empty author from the current RBAC username', () => {
    expect(manifestDraftFrom({}, '196045').author).toBe('196045')
    expect(manifestDraftFrom({ author: { name: '' } }, '196045').author).toBe('196045')
    expect(manifestDraftFrom({ author: 'original' }, '196045').author).toBe('original')
    expect(manifestDraftFrom({ author: { name: 'external' } }, '196045').author).toEqual({ name: 'external' })
  })
})

describe('structured SKILL.md helpers', () => {
  it('returns a complete empty form draft', () => {
    expect(emptySkillMdDraft()).toEqual({
      title: '',
      overview: '',
      inputs: '',
      steps: '',
      outputs: '',
      notes: '',
      examples: '',
      extra: '',
      extraFrontmatter: '',
    })
  })

  it('parses common bilingual sections and preserves unknown content', () => {
    const source = `---
name: imported-skill
description: Imported description
allowed-tools: Read, Bash
---

# Imported Skill

Use this skill for imported work.

## Inputs

A CSV file.

## 操作步骤

1. Read the file.

## Custom Policy

Keep this custom section.`

    const draft = parseSkillMd(source, { name: 'fallback' })

    expect(draft.title).toBe('Imported Skill')
    expect(draft.overview).toBe('Use this skill for imported work.')
    expect(draft.inputs).toBe('A CSV file.')
    expect(draft.steps).toBe('1. Read the file.')
    expect(draft.extra).toBe('## Custom Policy\n\nKeep this custom section.')
    expect(draft.extraFrontmatter).toBe('allowed-tools: Read, Bash')
  })

  it('composes valid frontmatter and all non-empty structured sections', () => {
    const draft = {
      ...emptySkillMdDraft(),
      title: 'CSV Cleaner',
      overview: 'Use when data needs cleaning.',
      steps: '1. Inspect input.\n2. Clean rows.',
      notes: 'Do not overwrite the source.',
      extra: '## Custom Policy\n\nKeep audit logs.',
      extraFrontmatter: 'allowed-tools: Read, Bash',
    }

    const result = composeSkillMd(draft, { name: 'csv-cleaner', description: 'Clean: CSV "safely"' })

    expect(result).toContain('name: "csv-cleaner"')
    expect(result).toContain('description: "Clean: CSV \\"safely\\""')
    expect(result).toContain('allowed-tools: Read, Bash')
    expect(result).toContain('# CSV Cleaner')
    expect(result).toContain('## 操作步骤\n\n1. Inspect input.')
    expect(result).toContain('## 注意事项\n\nDo not overwrite the source.')
    expect(result).toContain('## Custom Policy\n\nKeep audit logs.')
  })

  it('falls back to preserving malformed raw content as additional content', () => {
    const draft = parseSkillMd('plain content without headings', { name: 'fallback-name' })
    expect(draft.title).toBe('fallback-name')
    expect(draft.overview).toBe('plain content without headings')
  })
})

describe('isReservedBuildPath', () => {
  it('flags skill.yaml and SKILL.md', () => {
    expect(isReservedBuildPath('skill.yaml')).toBe(true)
    expect(isReservedBuildPath('SKILL.md')).toBe(true)
  })

  it('does not flag other paths', () => {
    expect(isReservedBuildPath('scripts/run.py')).toBe(false)
    expect(isReservedBuildPath('README.md')).toBe(false)
  })
})

describe('isSafeRelativePath', () => {
  it('accepts safe relative POSIX paths', () => {
    expect(isSafeRelativePath('scripts/run.py')).toBe(true)
    expect(isSafeRelativePath('assets/icon.png')).toBe(true)
  })

  it('rejects absolute paths, traversal, backslashes and drive letters', () => {
    expect(isSafeRelativePath('/etc/passwd')).toBe(false)
    expect(isSafeRelativePath('../secret')).toBe(false)
    expect(isSafeRelativePath('scripts/../../secret')).toBe(false)
    expect(isSafeRelativePath('scripts\\run.py')).toBe(false)
    expect(isSafeRelativePath('C:/Windows')).toBe(false)
  })

  it('rejects empty/blank paths', () => {
    expect(isSafeRelativePath('')).toBe(false)
    expect(isSafeRelativePath(null)).toBe(false)
    expect(isSafeRelativePath('scripts//run.py')).toBe(false)
  })
})

describe('dedupeList', () => {
  it('trims, drops empties and dedupes', () => {
    expect(dedupeList([' network ', 'network', '', '  ', 'filesystem'])).toEqual(['network', 'filesystem'])
  })

  it('handles an undefined/empty input', () => {
    expect(dedupeList(undefined)).toEqual([])
    expect(dedupeList([])).toEqual([])
  })
})

describe('api.js skill-build endpoint assembly', () => {
  let fetchMock

  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('window', { location: { origin: 'http://localhost' } })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('createGuidedBuild posts manifest/skillMd JSON to /skill-builds/guided', async () => {
    await createGuidedBuild({ namespace: 'demo' }, 'body')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skill-builds/guided')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ manifest: { namespace: 'demo' }, skillMd: 'body' })
  })

  it('getSkillBuild reads /skill-builds/{id}', async () => {
    await getSkillBuild('b1')
    const url = fetchMock.mock.calls[0][0]
    expect(url.pathname).toBe('/api/skill-builds/b1')
  })

  it('patchSkillBuild only includes manifest/skillMd when provided', async () => {
    await patchSkillBuild('b1', { expectedRevision: 3, manifest: { tags: ['x'] } })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skill-builds/b1')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ expectedRevision: 3, manifest: { tags: ['x'] } })
  })

  it('addSkillBuildFile posts multipart form fields', async () => {
    const file = new Blob(['x'])
    await addSkillBuildFile('b1', { path: 'scripts/run.py', expectedRevision: 2, file })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skill-builds/b1/files')
    expect(init.method).toBe('POST')
    expect(init.body.get('path')).toBe('scripts/run.py')
    expect(init.body.get('expectedRevision')).toBe('2')
  })

  it('deleteSkillBuildFile sends path/expectedRevision as query params', async () => {
    await deleteSkillBuildFile('b1', { path: 'scripts/run.py', expectedRevision: 4 })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skill-builds/b1/files')
    expect(init.method).toBe('DELETE')
    expect(url.searchParams.get('path')).toBe('scripts/run.py')
    expect(url.searchParams.get('expectedRevision')).toBe('4')
  })

  it('publishSkillBuild posts expectedRevision/confirmed', async () => {
    await publishSkillBuild('b1', { expectedRevision: 5, confirmed: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/skill-builds/b1/publish')
    expect(JSON.parse(init.body)).toEqual({ expectedRevision: 5, confirmed: true })
  })

  it('scanExternalSkill posts multipart file to /external-skill-scans', async () => {
    const file = new Blob(['zip'])
    await scanExternalSkill(file)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/external-skill-scans')
    expect(init.body.get('file').size).toBe(file.size)
  })

  it('selectExternalCandidates posts candidateIds JSON', async () => {
    await selectExternalCandidates('scan1', ['c1', 'c2'])
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.pathname).toBe('/api/external-skill-scans/scan1/selections')
    expect(JSON.parse(init.body)).toEqual({ candidateIds: ['c1', 'c2'] })
  })

  it('attaches status and structured detail to thrown errors', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: () => Promise.resolve({ detail: { message: 'stale revision', currentRevision: 6 } }),
    })
    await expect(getSkillBuild('b1')).rejects.toMatchObject({
      status: 409,
      message: 'stale revision',
      detail: { message: 'stale revision', currentRevision: 6 },
    })
  })
})
