// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../src/stores/auth.js'
import UploadView from '../src/views/UploadView.vue'
import BuildWorkspace from '../src/components/skillBuilds/BuildWorkspace.vue'
import {
  createGuidedBuild,
  getSkillBuild,
  patchSkillBuild,
} from '../src/lib/api.js'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key) => key }),
}))

vi.mock('../src/lib/api.js', () => ({
  uploadSkill: vi.fn(),
  createGuidedBuild: vi.fn(),
  scanExternalSkill: vi.fn(),
  selectExternalCandidates: vi.fn(),
  getSkillBuild: vi.fn(),
  patchSkillBuild: vi.fn(),
  addSkillBuildFile: vi.fn(),
  deleteSkillBuildFile: vi.fn(),
  publishSkillBuild: vi.fn(),
}))

function buildPreview(sourceType, author = '') {
  return {
    buildId: `${sourceType}-build`,
    sourceType,
    status: 'needs_input',
    revision: 1,
    expiresAt: '2026-07-15T12:00:00Z',
    manifest: {
      namespace: 'demo',
      name: 'csv-cleaner',
      version: '1.0.0',
      description: 'Clean CSV files.',
      author,
      license: 'MIT',
      runtime: 'claude-agent-skill',
      targets: ['claude'],
      dependencies: { python: [], system: [], skills: [] },
      permissions: [],
      tags: [],
    },
    manifestYaml: 'name: csv-cleaner',
    skillMd: '---\nname: csv-cleaner\ndescription: Clean CSV files.\n---\n\n# CSV Cleaner\n\nClean input data.\n\n## Steps\n\n1. Inspect rows.',
    missingFields: [],
    unconfirmedFields: [],
    detectedFacts: {},
    issues: [],
    tree: [],
    publishable: false,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.setRbacBridge({ username: '196045' }, [])
  vi.clearAllMocks()
  window.scrollTo = vi.fn()
})

describe('upload build author and structured editor flow', () => {
  it('starts a guided build with the current RBAC username', async () => {
    const preview = buildPreview('guided')
    createGuidedBuild.mockResolvedValue({ buildId: preview.buildId })
    getSkillBuild.mockResolvedValue(preview)

    const wrapper = mount(UploadView)
    await wrapper.get('.card-button.accent').trigger('click')
    await flushPromises()

    expect(createGuidedBuild).toHaveBeenCalledWith({ author: '196045' }, '')
  })

  it.each([
    ['guided', '', '196045'],
    ['external', '', '196045'],
    ['native_zip', 'package-author', 'package-author'],
  ])('shows prefilled author and structured SKILL.md for %s builds', async (sourceType, author, expectedAuthor) => {
    const preview = buildPreview(sourceType, author)
    getSkillBuild.mockResolvedValue(preview)
    patchSkillBuild.mockImplementation(async (_buildId, payload) => ({
      ...preview,
      revision: preview.revision + 1,
      manifest: payload.manifest,
      skillMd: payload.skillMd,
    }))

    const wrapper = mount(BuildWorkspace, { props: { buildId: preview.buildId } })
    await flushPromises()

    if (sourceType === 'native_zip') {
      await wrapper.findAll('.step-item')[1].trigger('click')
    } else {
      await wrapper.get('.next-button').trigger('click')
      await flushPromises()
    }

    expect(wrapper.get('input[placeholder="填写作者用户名"]').element.value).toBe(expectedAuthor)

    await wrapper.get('.next-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.skill-md-form').exists()).toBe(true)
    expect(wrapper.get('[data-skill-md-field="title"]').element.value).toBe('CSV Cleaner')
    expect(wrapper.get('[data-skill-md-field="steps"]').element.value).toBe('1. Inspect rows.')
  })
})
