// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import FeaturedWorkflowPacks from '../src/components/FeaturedWorkflowPacks.vue'
import SkillGovernancePanel from '../src/components/SkillGovernancePanel.vue'
import { reportSkillSignal } from '../src/lib/api.js'

vi.mock('../src/lib/api.js', () => ({ reportSkillSignal: vi.fn() }))

const governance = {
  compatibleExecutors: ['OpenCode 1.15.11', 'Codex'],
  requiredMcp: ['forgejo-read'],
  permissions: ['workspace:read', 'tests:run'],
  scanStatus: 'passed',
  examples: ['修复可复现的解析错误'],
  codeMapReferences: ['src/parser.py:42'],
  successRate: 0.8,
  testPassRate: 0.95,
  sampleSize: 10,
  failureReasons: { TEST_FAILED: 2 },
  taskContentCollected: false,
}

describe('community governance display', () => {
  beforeEach(() => { vi.clearAllMocks(); reportSkillSignal.mockResolvedValue(null) })

  it('renders compatibility, MCP, permissions, scan, Code Map, examples, and acceptance data', () => {
    const wrapper = mount(SkillGovernancePanel, {
      props: { namespace: 'skillify', name: 'bugfix', version: '1.0.0', governance },
    })
    const text = wrapper.text()
    for (const value of ['OpenCode 1.15.11', 'forgejo-read', 'workspace:read', 'passed', 'src/parser.py:42', '80%', '10 次']) {
      expect(text).toContain(value)
    }
    expect(text).toContain('任务内容默认不采集：是')
  })

  it('does not invent percentages with no samples and reports bounded signals only', async () => {
    const wrapper = mount(SkillGovernancePanel, {
      props: {
        namespace: 'skillify', name: 'bugfix', version: '1.0.0',
        governance: { ...governance, sampleSize: 0, successRate: null, testPassRate: null },
      },
    })
    expect(wrapper.text()).toContain('不展示推测百分比')
    await wrapper.findAll('footer button')[1].trigger('click')
    expect(reportSkillSignal).toHaveBeenCalledWith('skillify', 'bugfix', '1.0.0', 'run', true)
  })

  it('renders three team-curated workflow packs', () => {
    const wrapper = mount(FeaturedWorkflowPacks)
    expect(wrapper.findAll('article')).toHaveLength(3)
    expect(wrapper.text()).toContain('Evidence Bugfix')
  })
})
