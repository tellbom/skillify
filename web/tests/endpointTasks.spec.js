// @vitest-environment jsdom
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EndpointTasksView from '../src/views/EndpointTasksView.vue'
import { dispatchEndpointTask, getEndpointTasks, getMyEndpoints } from '../src/lib/api.js'

vi.mock('../src/lib/api.js', () => ({
  getMyEndpoints: vi.fn(),
  getEndpointTasks: vi.fn(),
  dispatchEndpointTask: vi.fn(),
}))

const endpoint = {
  endpointId: 'endpoint-1', label: 'Developer laptop', online: true,
  workspaceAliases: ['billing'], lastSeenAt: '2026-07-16T10:00:00Z',
}

describe('EndpointTasksView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMyEndpoints.mockResolvedValue([endpoint])
    getEndpointTasks.mockResolvedValue([{
      taskId: 'task-old', endpointId: 'endpoint-1', workflowId: 'evidence-review',
      runtime: 'opencode',
      state: 'failed', events: [{
        eventType: 'task.failed', occurredAt: '2026-07-16T10:02:00Z',
        failureReason: 'TEST_FAILED',
        testSummary: { passed: 12, failed: 1, skipped: 2 },
        diffStats: { filesChanged: 3, insertions: 24, deletions: 7 },
        artifacts: [{ artifactId: 'artifact-1', kind: 'test-report' }],
      }],
    }])
  })

  it('renders fixed workflow controls and verifiable timeline without prompt or shell fields', async () => {
    const wrapper = mount(EndpointTasksView)
    await flushPromises()

    expect(wrapper.get('[data-testid="workflow-select"]').findAll('option')).toHaveLength(5)
    expect(wrapper.get('[data-testid="runtime-select"]').findAll('option')).toHaveLength(2)
    expect(wrapper.text()).toContain('TEST_FAILED')
    expect(wrapper.text()).toContain('12 passed · 1 failed · 2 skipped')
    expect(wrapper.text()).toContain('3 files · +24 / -7')
    expect(wrapper.text()).toContain('test-report:artifact-1')
    expect(wrapper.find('[name="prompt"]').exists()).toBe(false)
    expect(wrapper.find('[name="shell"]').exists()).toBe(false)
  })

  it('dispatches only the selected fixed form payload', async () => {
    dispatchEndpointTask.mockResolvedValue({
      taskId: 'task-new', workflowId: 'evidence-bugfix', runtime: 'claude-code', state: 'awaiting_confirmation', events: [],
    })
    const wrapper = mount(EndpointTasksView)
    await flushPromises()
    await wrapper.get('[data-testid="runtime-select"]').setValue('claude-code')
    await wrapper.get('[data-testid="workflow-input"]').setValue('BUG-42')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(dispatchEndpointTask).toHaveBeenCalledWith({
      endpointId: 'endpoint-1', workspaceAlias: 'billing',
      runtime: 'claude-code',
      workflowId: 'evidence-bugfix', workflowVersion: '1.0.0',
      inputs: { issueReference: 'BUG-42' },
    })
    expect(wrapper.text()).toContain('task-new')
  })
})
